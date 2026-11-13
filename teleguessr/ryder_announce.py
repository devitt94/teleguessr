"""Automatic Ryder Cup posts at the start and end of a round.

The two entry points here are the only things the rest of the bot calls. Both
are no-ops when no cup is drawn, and both swallow every exception: a problem in
the cup must never interrupt a round, so the worst case is a missing message
and a line in the log.
"""

from pathlib import Path

from loguru import logger

from teleguessr.gross_formatters import split_message
from teleguessr.ryder_cup import (
    find_current_league_file,
    league_date_from_path,
    load_cup,
    load_current_standings,
)
from teleguessr.ryder_formatters import (
    format_day_result_html,
    format_round_preview_html,
)


async def _post(bot, chat_id: int, message: str) -> None:
    for chunk in split_message(message):
        await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="HTML")


async def announce_round_start(
    bot, chat_id: int, data_dir: Path, round_number: int
) -> None:
    """Post the day's format and pairings. Silent if no cup is running."""
    try:
        league_file = find_current_league_file(data_dir)
        if league_file is None:
            return

        cup = load_cup(data_dir, league_date_from_path(league_file))
        if cup is None:
            return

        message = format_round_preview_html(cup, round_number)
        if message:
            await _post(bot, chat_id, message)
    except Exception:
        logger.exception("Ryder Cup round-start announcement failed")


async def announce_round_end(
    bot, chat_id: int, data_dir: Path, round_number: int
) -> None:
    """Post the day's match results and the new score. Silent if no cup."""
    try:
        standings = load_current_standings(data_dir)
        if standings is None:
            return

        message = format_day_result_html(standings, round_number)
        if message:
            await _post(bot, chat_id, message)
    except Exception:
        logger.exception("Ryder Cup round-end announcement failed")
