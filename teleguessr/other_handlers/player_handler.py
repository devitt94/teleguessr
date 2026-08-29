"""Telegram handlers for /player: a pick-list of players and their full profile.

Independent of BotManager -- these only need the data directory, so wiring them
up costs main.py three lines.
"""

from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from teleguessr.other_handlers.gross_formatters import split_message
from teleguessr.other_handlers.player_formatters import (
    format_player_list_html,
    format_player_profile_html,
)
from teleguessr.other_handlers.player_stats import (
    compute_player_profile,
    list_players,
    resolve_player,
)


PLAYER_STATS_CALLBACK_PREFIX = "pstats:"
# Telegram rejects callback_data over 64 bytes.
MAX_CALLBACK_DATA_BYTES = 64

HandlerFunc = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def encode_callback_data(player: str) -> str:
    """Pack a player name into callback data, truncating safely if it is huge."""
    budget = MAX_CALLBACK_DATA_BYTES - len(PLAYER_STATS_CALLBACK_PREFIX.encode())
    encoded = player.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
    return f"{PLAYER_STATS_CALLBACK_PREFIX}{encoded}"


def decode_callback_data(data: str, players: list[str]) -> str | None:
    """Resolve callback data back to a known player, tolerating truncation."""
    name = data.removeprefix(PLAYER_STATS_CALLBACK_PREFIX)
    if name in players:
        return name

    matches = [player for player in players if player.startswith(name)]
    return matches[0] if len(matches) == 1 else None


def build_player_keyboard(players: list[str]) -> InlineKeyboardMarkup:
    """One player per row -- the names are far too long to sit side by side."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(player, callback_data=encode_callback_data(player))]
            for player in players
        ]
    )


async def _send_profile(message, data_dir: Path, player: str) -> None:
    profile = compute_player_profile(data_dir, player)
    if profile is None:
        await message.reply_text(f"No completed rounds on record for {player}.")
        return

    for chunk in split_message(format_player_profile_html(profile)):
        await message.reply_text(chunk, parse_mode="HTML")


def build_player_command_handler(data_dir: Path) -> HandlerFunc:
    """/player [name] -- a pick-list, or a profile if the name is unambiguous."""

    async def player_handler(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = " ".join(context.args) if context.args else ""

        try:
            matches = resolve_player(data_dir, query)
        except Exception:
            logger.exception("Failed to list players")
            await update.message.reply_text(
                "⚠️ Couldn't read the player list — check the bot logs."
            )
            return

        if not matches:
            await update.message.reply_text(
                f"No player matching “{query}”. Send /player to see the full list."
            )
            return

        if query and len(matches) == 1:
            try:
                await _send_profile(update.message, data_dir, matches[0])
            except Exception:
                logger.exception("Failed to build profile for %s", matches[0])
                await update.message.reply_text(
                    "⚠️ Couldn't build that profile — check the bot logs."
                )
            return

        await update.message.reply_text(
            format_player_list_html(matches),
            parse_mode="HTML",
            reply_markup=build_player_keyboard(matches),
        )

    return player_handler


def build_player_callback_handler(data_dir: Path) -> HandlerFunc:
    """Handles a tap on one of the /player buttons."""

    async def player_callback_handler(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        await query.answer()

        try:
            player = decode_callback_data(query.data, list_players(data_dir))
            if player is None:
                await query.message.reply_text(
                    "That player is no longer on the list — send /player again."
                )
                return
            await _send_profile(query.message, data_dir, player)
        except Exception:
            logger.exception("Failed to handle player callback %s", query.data)
            await query.message.reply_text(
                "⚠️ Couldn't build that profile — check the bot logs."
            )

    return player_callback_handler
