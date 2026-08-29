"""Telegram command handler for the handicap-free stats table.

Kept independent of BotManager: the handler only needs the data directory, so
registering it costs main.py two lines and touches nothing else.
"""

from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger
from telegram import Update
from telegram.ext import ContextTypes

from teleguessr.other_handlers.gross_formatters import (
    format_gross_stats_html,
    split_message,
)
from teleguessr.other_handlers.gross_stats import SortKey, compute_gross_stats


HandlerFunc = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def build_gross_stats_handler(data_dir: Path) -> HandlerFunc:
    """Build a /gross handler reading finished leagues from data_dir."""
    finished_league_dir = data_dir / "leagues" / "finished"

    async def gross_stats_handler(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        sort_key = SortKey.parse(context.args[0] if context.args else None)

        try:
            table = compute_gross_stats(finished_league_dir)
        except Exception:
            logger.exception("Failed to compute gross stats")
            await update.message.reply_text(
                "⚠️ Couldn't compute the gross stats — check the bot logs."
            )
            return

        message = format_gross_stats_html(table, sort_key)
        for chunk in split_message(message):
            await update.message.reply_text(chunk, parse_mode="HTML")

    return gross_stats_handler
