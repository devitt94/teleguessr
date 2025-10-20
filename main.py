from datetime import UTC, datetime
import os
from pathlib import Path
import re
import traceback
from formatters import format_round_result, format_scoreboard
from league import LeagueState
import asyncio

import dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes,
)
from geoguessr_scraper import get_challenge_scores

from settings import TIME_PER_ROUND_HOURS

from loguru import logger

# Load environment variables
dotenv.load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LEAGUE_FILE = Path("data/league.json")
CHALLENGE_REGEX = r"(https?://www\.geoguessr\.com/challenge/[a-zA-Z0-9]+)"
ADMIN_ID = os.getenv("ADMIN_TELEGRAM_ID")

# In-memory league state
league_state: LeagueState | None = None


async def start_league(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global league_state
    if league_state is None or league_state.is_finished:
        league_state = LeagueState(filepath=LEAGUE_FILE)
        await update.message.reply_text(
            "🏁 GeoGuessr League started! Post the first challenge link."
        )
    else:
        await update.message.reply_text("A league is already running.")
        return


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    match = re.search(CHALLENGE_REGEX, text)

    ready_for_challenge = (
        (league_state is not None)
        and (not league_state.round_in_progress)
        and (not league_state.is_finished)
    )

    if not match or not ready_for_challenge:
        return

    challenge_url = match.group(0)
    league_state.start_round(challenge_url, TIME_PER_ROUND_HOURS)
    league_state.save()

    await update.message.reply_text(
        f"🌍 Challenge {league_state.current_round_num} detected!\n"
        f"Timer started: {TIME_PER_ROUND_HOURS} hours from now.\n"
        f"{challenge_url}"
    )

    # Start countdown in background
    delay = int(TIME_PER_ROUND_HOURS * 3600)
    asyncio.create_task(
        countdown_and_scrape(context, update.effective_chat.id, challenge_url, delay)
    )


async def countdown_and_scrape(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: str,
    challenge_url: str,
    delay_seconds: int,
) -> None:
    if delay_seconds > 3600:
        logger.info("Starting 1 hour warning countdown...")
        one_hour_warning_countdown = delay_seconds - 3600
        await asyncio.sleep(one_hour_warning_countdown)

        await context.bot.send_message(
            chat_id,
            "1 hour remaining",
        )

        delay_seconds = 3600

    logger.info("Starting final countdown...")
    await asyncio.sleep(delay_seconds)
    try:
        round_result = await get_challenge_scores(challenge_url)

        league_state.add_round_result(round_result)
        league_state.save()

        round_result_table = format_round_result(round_result)
        round_result_text = f"⏰ Time's up - Here are the results for challenge {league_state.current_round_num - 1}:\n{round_result_table}"
        await context.bot.send_message(
            chat_id, round_result_text, parse_mode="MarkdownV2"
        )

        league_standings_table = format_scoreboard(league_state.leaderboard)
        league_standings_text = (
            f"📊 Current League Standings:\n{league_standings_table}"
        )
        await context.bot.send_message(
            chat_id, league_standings_text, parse_mode="MarkdownV2"
        )

        if league_state.is_finished:
            await context.bot.send_message(
                chat_id, f"🏆 League finished. Winner: {league_state.winner}"
            )
        else:
            await context.bot.send_message(
                chat_id,
                f"Next challenge, please! ({league_state.current_round_num}/{league_state.num_rounds})",
            )
    except Exception as e:
        await context.bot.send_message(
            ADMIN_ID, f"Countdown error for {challenge_url}\n\n{e}"
        )
        raise  # op


async def restore_timers_post_init(app):
    global league_state
    if league_state is None or not league_state.round_in_progress:
        return

    current_time = datetime.now(UTC).replace(tzinfo=None)
    delay = max(
        int((league_state.current_round.end_time - current_time).total_seconds()),
        0,
    )
    logger.info(f"Restoring timer with {delay} seconds remaining...")
    asyncio.create_task(
        countdown_and_scrape(
            app.bot, None, league_state.current_round.challenge_url, delay
        )
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

    # Try sending alert to admin
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
        f"📋 Latest Round Results:\n{latest_round_text}", parse_mode="MarkdownV2"
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

    app = ApplicationBuilder().token(TOKEN).post_init(restore_timers_post_init).build()
    app.add_handler(CommandHandler("startleague", start_league))
    app.add_handler(CommandHandler("leaderboard", show_leaderboard))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    logger.info("Bot running...")
    app.run_polling()

    logger.info("Bot stopped.")


if __name__ == "__main__":
    main()
