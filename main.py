import asyncio
import os
from pathlib import Path
import traceback
from formatters import format_round_result_html, format_leaderboard_html
from league import LeagueState
import dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from geoguessr_scraper import create_challenge, get_challenge_scores
from awards import get_best_and_worst_guesses

from settings import TIME_PER_ROUND_HOURS

from loguru import logger

# Load environment variables
dotenv.load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LEAGUE_FILE = Path("data/league.json")
ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID"))
MAP_ID = os.getenv("MAP_ID")
TIME_LIMIT_PER_GUESS_SECONDS = int(os.getenv("TIME_LIMIT_PER_GUESS_SECONDS", "90"))


async def send_markdown_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message: str,
):
    """Send a markdown-formatted message to a chat."""
    
    def escape_markdown_v2(text: str) -> str:
        """Escape characters for Telegram MarkdownV2."""
        to_escape = r'_*[]()~`>#+-=|{}.!'
        return ''.join("\\" + c if c in to_escape else c for c in text)
    
    message = escape_markdown_v2(message)
    
    await context.bot.send_message(
        chat_id=chat_id,
        text=message,
        parse_mode="MarkdownV2",
    )

async def send_html_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message: str,
):
    """Send an HTML-formatted message to a chat."""
    await context.bot.send_message(
        chat_id=chat_id,
        text=message,
        parse_mode="HTML",
    )


async def start_league(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != int(ADMIN_ID):
        await update.message.reply_text("You are not authorized to use this command.")
        return

    global league_state
    if (
        league_state is None
        or league_state.is_finished
        or not league_state.round_in_progress
    ):
        league_state = LeagueState(filepath=LEAGUE_FILE)
        await update.message.reply_text("🏁 GeoGuessr League started!")

        new_round_url = await create_challenge(
            map_id=MAP_ID,
            time_limit_seconds=TIME_LIMIT_PER_GUESS_SECONDS,
        )

        league_state.start_round(url=new_round_url, hours=TIME_PER_ROUND_HOURS)
        league_state.save()
        await context.bot.send_message(
            update.effective_chat.id,
            f"First round started! URL: {new_round_url}",
        )
    else:
        await update.message.reply_text("A league is already running.")
        return


async def end_round(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.effective_user.id != int(ADMIN_ID):
        await update.message.reply_text("You are not authorized to use this command.")
        return

    global league_state
    if league_state is None or not league_state.round_in_progress:
        await update.message.reply_text("No round is currently in progress.")
        return

    challenge_url = league_state.current_round.challenge_url
    chat_id = update.effective_chat.id
    round_result = await get_challenge_scores(challenge_url)

    round_result.awards = get_best_and_worst_guesses(round_result)

    league_state.add_round_result(round_result)
    league_state.save()

    round_text = format_round_result_html(round_result)
    
    await send_html_message(
        context,
        update.effective_chat.id,
        f"Round {league_state.last_round_finished_num} Results:\n\n{round_text}",
    )

    await show_leaderboard(update, context)

    if league_state.is_finished:
        winner = league_state.get_winner()
        await context.bot.send_message(chat_id, f"🏆 League finished. Winner: {winner}")
    else:
        new_round_url = await create_challenge(
            map_id=MAP_ID,
            time_limit_seconds=TIME_LIMIT_PER_GUESS_SECONDS,
        )

        league_state.start_round(url=new_round_url, hours=TIME_PER_ROUND_HOURS)
        league_state.save()

        await context.bot.send_message(
            chat_id,
            f"Round {league_state.current_round_num} started! URL: {new_round_url}",
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler that sends the traceback to the admin."""
    # Build a clean traceback message
    tb_list = traceback.format_exception(
        None, context.error, context.error.__traceback__
    )
    tb_text = "".join(tb_list)

    message = (
        "⚠️ <b>Bot Handler Error</b>\n"
        f"<b>Exception:</b> {context.error}\n\n"
        f"<b>Traceback:</b>\n<pre>{tb_text}</pre>"
    )

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID, text=message, parse_mode="HTML"
        )
    except Exception as e:
        logger.exception(f"Failed to send admin alert: {e}")

    # Still print to logs
    logger.info(f"Exception while handling update {update}: {context.error}")


async def show_leaderboard(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
):
    global league_state
    if league_state is None:
        await update.message.reply_text("No league is currently running.")
        return

    latest_round = league_state.results[-1] if league_state.results else None
    if latest_round is None:
        await update.message.reply_text("No rounds have been played yet.")
        return

    leaderboard_text = format_leaderboard_html(**league_state.leaderboard_detail)
    await send_html_message(
        context,
        update.effective_chat.id,
        f"📊 Standings after round {league_state.last_round_finished_num}:\n\n{leaderboard_text}",
    )


async def remind_players(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    global league_state
    if league_state is None or not league_state.round_in_progress:
        await update.message.reply_text("No round is currently in progress.")
        return

    challenge_url = league_state.current_round.challenge_url
    chat_id = update.effective_chat.id

    current_result = await get_challenge_scores(challenge_url)
    players_finished = current_result.players_finished
    from settings import PLAYER_SHORTNAMES
    players_expected = set(PLAYER_SHORTNAMES.keys())

    players_pending = players_expected - players_finished
    if not players_pending:
        await context.bot.send_message(
            chat_id,
            f"All players have finished round {league_state.current_round_num}!",
        )
        return
    pending_list = "\n".join(f"- {player}" for player in players_pending)
    await context.bot.send_message(
        chat_id,
        f"⏰ Reminder: The following players have not yet completed round {league_state.current_round_num}:\n{pending_list}"
        f"\n\nRound URL: {challenge_url}",
    )


async def simulate_league(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Simulate a full league with given challenge URLs for testing purposes."""


    challenge_urls = [
        "https://www.geoguessr.com/challenge/q1jl07AoTdu9XqVr",
        "https://www.geoguessr.com/challenge/TBoioOIrdqrFZJIQ",
        "https://www.geoguessr.com/challenge/gVmY1NVOqnaHnHy4",
        "https://www.geoguessr.com/challenge/KGI2gHP15ejmDGVg",
        "https://www.geoguessr.com/challenge/989O8zGW1iWsfrsu",
    ]
    random_str = os.urandom(4).hex()
    sim_league_state = LeagueState(filepath=f"data/simulated_league_{random_str}.json", num_rounds=len(challenge_urls))
    for url in challenge_urls:
        
        sim_league_state.start_round(url=url, hours=1)

        # Simulate waiting for round to end
        round_result = await get_challenge_scores(url)

        round_result.awards = get_best_and_worst_guesses(round_result)

        sim_league_state.add_round_result(round_result)
        sim_league_state.save()

        
        latest_round_text = format_round_result_html(round_result)
        await send_html_message(
            context,
            update.effective_chat.id,
            f"Round {sim_league_state.current_round_num} Results:\n\n{latest_round_text}",
        )
        
        leaderboard_text = format_leaderboard_html(**sim_league_state.leaderboard_detail)
        await send_html_message(
            context,
            update.effective_chat.id,
            f"📊 Standings after round {sim_league_state.last_round_finished_num}:\n\n{leaderboard_text}",
        )

        await asyncio.sleep(5)  # Small delay to avoid flooding


    winner = sim_league_state.get_winner()
    await context.bot.send_message(update.effective_chat.id, f"🏆 League finished. Winner: {winner}")



def main():
    global league_state
    league_state = LeagueState(filepath=LEAGUE_FILE)
    league_state.load_from_file()

    logger.info(
        "League state loaded is {}".format(
            "finished"
            if league_state.is_finished
            else "in progress"
            if league_state.round_in_progress
            else "not started"
        )
    )

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("startleague", start_league))
    app.add_handler(CommandHandler("leaderboard", show_leaderboard))
    app.add_handler(CommandHandler("endround", end_round))
    app.add_handler(CommandHandler("remind", remind_players))
    app.add_handler(CommandHandler("simulateTestLeague", simulate_league))
    app.add_error_handler(error_handler)
    logger.info("Bot running...")
    app.run_polling()

    logger.info("Bot stopped.")


if __name__ == "__main__":
    main()
