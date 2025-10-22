import os
from pathlib import Path
import traceback
from formatters import format_round_result, format_scoreboard
from league import LeagueState
import dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from geoguessr_scraper import create_challenge, get_challenge_scores

from settings import TIME_PER_ROUND_HOURS

from loguru import logger

# Load environment variables
dotenv.load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LEAGUE_FILE = Path("data/league.json")
ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID"))
MAP_ID = os.getenv("MAP_ID")
TIME_LIMIT_PER_GUESS_SECONDS = int(os.getenv("TIME_LIMIT_PER_GUESS_SECONDS", "90"))


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

    league_state.add_round_result(round_result)
    league_state.save()

    await show_leaderboard(update, context)

    if league_state.is_finished:
        await context.bot.send_message(
            chat_id, f"🏆 League finished. Winner: {league_state.winner}"
        )
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
        logger.info(f"Failed to send admin alert: {e}")

    # Still print to logs
    logger.info(f"Exception while handling update {update}: {context.error}")


async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global league_state
    if league_state is None:
        update.message.reply_text("No league is currently running.")
        return

    latest_round = league_state.results[-1] if league_state.results else None
    if latest_round is None:
        update.message.reply_text("No rounds have been played yet.")
        return

    latest_round_text = format_round_result(latest_round)
    await update.message.reply_text(
        f"Round {league_state.current_round_num - 1} Results:\n{latest_round_text}",
        parse_mode="MarkdownV2",
    )

    leaderboard_text = format_scoreboard(league_state.leaderboard)
    await update.message.reply_text(
        f"📊 Current League Standings:\n{leaderboard_text}", parse_mode="MarkdownV2"
    )


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
    app.add_error_handler(error_handler)
    logger.info("Bot running...")
    app.run_polling()

    logger.info("Bot stopped.")


if __name__ == "__main__":
    main()
