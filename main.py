from datetime import datetime
import os
from pathlib import Path
import re
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

# Load environment variables
dotenv.load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LEAGUE_FILE = Path("data/league.json")
CHALLENGE_REGEX = r"(https?://www\.geoguessr\.com/challenge/[a-zA-Z0-9]+)"

# In-memory league state
league_state: LeagueState | None = None


def format_scoreboard(scores: dict) -> str:
    # Sort by score (descending)
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    # Determine column widths
    name_width = max(len(name) for name, _ in sorted_scores) + 2
    score_width = 10

    lines = [
        f"{'Player'.ljust(name_width)}| {'Total Score'.rjust(score_width)}",
        "-" * (name_width + score_width + 2),
    ]
    for name, score in sorted_scores:
        lines.append(f"{name.ljust(name_width)}| {str(score).rjust(score_width)}")

    table = "```\n" + "\n".join(lines) + "\n```"
    return table


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
    await asyncio.sleep(delay_seconds)

    round_result = await get_challenge_scores(challenge_url)

    league_state.add_round_result(round_result)
    league_state.save()

    # Send update message
    scoreboard_text = format_scoreboard(league_state.leaderboard)
    await context.bot.send_message(chat_id, scoreboard_text, parse_mode="MarkdownV2")

    if league_state.is_finished:
        await context.bot.send_message(
            chat_id, f"🏆 League finished. Winner: {league_state.winner}"
        )
    else:
        await context.bot.send_message(
            chat_id,
            f"Next challenge, please! ({league_state.current_round_num}/{league_state.num_rounds})",
        )


async def restore_timers_post_init(app):
    global league_state
    if league_state is None or not league_state.round_in_progress:
        return

    delay = max(
        int((league_state.current_round.end_time - datetime.utcnow()).total_seconds()),
        0,
    )
    print(f"Restoring timer with {delay} seconds remaining...")
    asyncio.create_task(
        countdown_and_scrape(
            app.bot, None, league_state.current_round.challenge_url, delay
        )
    )


def main():
    global league_state
    league_state = LeagueState(filepath=LEAGUE_FILE)
    league_state.load_from_file()

    print(
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot running...")
    app.run_polling()

    print("Bot stopped.")


if __name__ == "__main__":
    main()
