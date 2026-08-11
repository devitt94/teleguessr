"""Telegram handlers for the Ryder Cup.

Phase one is deliberately quiet: nothing is posted unless somebody asks for it,
so bot_manager.py stays untouched and the cup cannot interfere with a league in
progress.
"""

import json
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from teleguessr.gross_formatters import split_message
from teleguessr.ryder_cup import (
    RyderCup,
    clear_signup,
    cup_path,
    draw_cup,
    find_current_league_file,
    league_date_from_path,
    load_cup,
    load_current_standings,
    load_signup,
    save_cup,
    save_signup,
)
from teleguessr.ryder_formatters import (
    format_draw_html,
    format_scorecard_html,
    format_signup_html,
    format_standings_html,
)
from teleguessr.settings import TELEGRAM_ID_TO_PLAYER_NAME


RYDER_OPT_IN_CALLBACK = "ryder_optin"
MIN_PLAYERS = 4

HandlerFunc = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def league_active_players(data_dir: Path) -> set[str]:
    """Read the league's opt-in list without touching PlayerManager.

    PlayerManager creates the file on construction, and this layer must never
    write to anything outside data/ryder/.
    """
    path = data_dir / "active_players" / "active_players.json"
    if not path.exists():
        return set()
    try:
        with path.open("r") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError):
        return set()


def _signup_markup(count: int) -> InlineKeyboardMarkup:
    label = "🏆 I'm in" if not count else f"🏆 I'm in ({count} signed up)"
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=RYDER_OPT_IN_CALLBACK)]]
    )


def build_ryder_signup_handler(data_dir: Path, admin_id: int) -> HandlerFunc:
    """/rydersignup — admin only. Opens sign-up for the next cup."""

    async def ryder_signup_handler(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if update.effective_user.id != admin_id:
            await update.message.reply_text(
                "Only the admin can open Ryder Cup sign-up."
            )
            return

        signup = load_signup(data_dir)
        save_signup(data_dir, signup)

        await update.message.reply_text(
            format_signup_html(signup.opted_in),
            parse_mode="HTML",
            reply_markup=_signup_markup(len(signup.opted_in)),
        )

    return ryder_signup_handler


def build_ryder_opt_in_handler(data_dir: Path) -> HandlerFunc:
    """Handles a tap on the Ryder Cup sign-up button."""

    async def ryder_opt_in_handler(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        player = TELEGRAM_ID_TO_PLAYER_NAME.get(query.from_user.id)

        if player is None:
            await query.answer("I don't recognise you as a league player.")
            return

        active = league_active_players(data_dir)
        if active and player not in active:
            await query.answer("Sign up for the league first!")
            return

        signup = load_signup(data_dir)
        if not signup.add(player):
            await query.answer("You're already in!")
            return

        save_signup(data_dir, signup)
        await query.answer("You're in the Ryder Cup! 🏆")

        try:
            await query.edit_message_text(
                format_signup_html(signup.opted_in),
                parse_mode="HTML",
                reply_markup=_signup_markup(len(signup.opted_in)),
            )
        except Exception:
            logger.warning("Could not update the Ryder Cup sign-up message")

    return ryder_opt_in_handler


def build_ryder_draw_handler(data_dir: Path, admin_id: int) -> HandlerFunc:
    """/ryderdraw — admin only. Closes sign-up and draws the teams."""

    async def ryder_draw_handler(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if update.effective_user.id != admin_id:
            await update.message.reply_text("Only the admin can draw the Ryder Cup.")
            return

        league_file = find_current_league_file(data_dir)
        if league_file is None:
            await update.message.reply_text(
                "No league found. Start the league first, then draw the cup."
            )
            return

        league_date = league_date_from_path(league_file)
        if load_cup(data_dir, league_date) is not None:
            await update.message.reply_text(
                "A cup has already been drawn for this league. "
                f"Delete {cup_path(data_dir, league_date).name} to redraw."
            )
            return

        signup = load_signup(data_dir)
        if len(signup.opted_in) < MIN_PLAYERS:
            await update.message.reply_text(
                f"Only {len(signup.opted_in)} signed up — need at least "
                f"{MIN_PLAYERS}. Run /rydersignup to open it up."
            )
            return

        with league_file.open("r") as f:
            num_rounds = json.load(f).get("num_rounds", 5)

        try:
            cup: RyderCup = draw_cup(
                league_date=league_date,
                num_rounds=num_rounds,
                players=signup.opted_in,
            )
        except ValueError as error:
            await update.message.reply_text(f"Couldn't draw the cup: {error}")
            return

        save_cup(data_dir, cup)
        clear_signup(data_dir)

        for chunk in split_message(format_draw_html(cup)):
            await update.message.reply_text(chunk, parse_mode="HTML")

    return ryder_draw_handler


def _build_standings_handler(data_dir: Path, formatter) -> HandlerFunc:
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            standings = load_current_standings(data_dir)
        except Exception:
            logger.exception("Failed to compute Ryder Cup standings")
            await update.message.reply_text(
                "⚠️ Couldn't work out the Ryder Cup standings — check the logs."
            )
            return

        if standings is None:
            await update.message.reply_text(
                "No Ryder Cup drawn for the current league. "
                "The admin can start one with /rydersignup."
            )
            return

        for chunk in split_message(formatter(standings)):
            await update.message.reply_text(chunk, parse_mode="HTML")

    return handler


def build_ryder_handler(data_dir: Path) -> HandlerFunc:
    """/ryder — current score, and the next day's draw."""
    return _build_standings_handler(data_dir, format_standings_html)


def build_ryder_card_handler(data_dir: Path) -> HandlerFunc:
    """/rydercard — every match played so far."""
    return _build_standings_handler(data_dir, format_scorecard_html)
