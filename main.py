#!/usr/bin/env python3

import asyncio
from enum import Enum
import json

from loguru import logger

from teleguessr.analysis import average_scores, round_analysis
from teleguessr.geoguessr_scraper import GeoguessrClient
from teleguessr.league import get_last_finished_league_id
from teleguessr.replay import replay_league
from teleguessr.settings import AppSettings, get_settings
from teleguessr.bot_manager import BotManager
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
)
import typer


async def initlise_bot_manager(
    settings: AppSettings, test_mode: bool = False
) -> BotManager:
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    geoguessr_client = GeoguessrClient(ncfa_cookie=settings.geoguessr_ncfa_cookie)

    if test_mode:
        latest_league_file = list(
            (settings.data_dir / "leagues" / "finished").glob("league_*.json")
        )[0]

        with open(latest_league_file, "r") as f:
            league_data = json.load(f)

        challenge_urls = [
            round_info["challenge_url"] for round_info in league_data["results"]
        ]
        round_index = 0

        async def create_fake_challenge(
            map_id: str,
            time_limit_seconds: int,
        ) -> str:
            """Create a fake challenge URL for testing purposes."""
            nonlocal round_index

            round_url = challenge_urls[round_index % len(challenge_urls)]
            round_index += 1
            return round_url

        geoguessr_client.create_challenge = create_fake_challenge
        settings.league.round_end_time_hour_utc = -1

    bot_manager = BotManager(
        admin_id=settings.telegram_admin_id,
        players_lounge_group_id=settings.telegram_players_lounge_group_id,
        data_dir=settings.data_dir,
        polling_interval_seconds=settings.polling_interval_seconds,
        league_settings=settings.league,
        geoguessr_client=geoguessr_client,
    )
    await bot_manager.initialise()
    return bot_manager


def main(test_mode: bool = False):
    settings = get_settings()

    settings.data_dir.mkdir(parents=True, exist_ok=True)

    bot_manager = asyncio.run(initlise_bot_manager(settings, test_mode))
    logger.info("BotManager initialised.")

    app = ApplicationBuilder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("startleague", bot_manager.start_league_handler))
    app.add_handler(CommandHandler("endround", bot_manager.end_round_handler))
    app.add_handler(CommandHandler("status", bot_manager.status_handler))
    app.add_handler(CommandHandler("lounge", bot_manager.lounge_handler))
    app.add_error_handler(bot_manager.error_handler)
    logger.info("Bot running...")

    asyncio.run(bot_manager.resume_league_tasks(app))

    app.run_polling()

    logger.info("Bot stopped.")


app = typer.Typer(
    help="Teleguessr Bot - Manage Geoguessr leagues via Telegram.",
)


@app.command()
def run_bot(
    test: bool = typer.Option(
        False, "--test", "-t", help="Run the bot in test mode with replayed challenges."
    ),
):
    """Run the Teleguessr Telegram Bot."""
    main(test_mode=test)


@app.command()
def replay(
    league_id: int = typer.Option(
        None,
        "--league-id",
        "-l",
        help="ID of the league to replay. Defaults to the latest finished league.",
    ),
    include_handicaps: bool = typer.Option(
        False,
        "--include-handicaps",
        "-i",
        help="Include handicaps when replaying the league.",
    ),
):
    """Replay a finished league for analysis."""

    settings = get_settings()

    finished_league_dir = settings.data_dir / "leagues" / "finished"
    if league_id is None:
        league_id = get_last_finished_league_id(finished_league_dir)

    league_file = finished_league_dir / f"league_{league_id}.json"

    if not league_file.exists():
        logger.error(f"League file {league_file} does not exist.")
        return

    handicaps_file = (
        settings.data_dir / "handicaps" / f"handicaps_league_{league_id}.json"
    )
    with open(handicaps_file, "r") as f:
        handicaps = json.load(f)

    if not include_handicaps:
        handicaps = {player: 0.0 for player in handicaps.keys()}

    asyncio.run(
        replay_league(
            league_path=league_file,
            handicaps=handicaps,
            league_settings=settings.league,
            show_handicap_adjustments=include_handicaps,
        )
    )


class AnalysisType(str, Enum):
    AVERAGE_SCORES = "avg"
    BEST_AND_WORST = "min_max"
    ALL = "all"


@app.command()
def analysis(
    _type: AnalysisType = typer.Option(
        AnalysisType.ALL,
        "--type",
        "-t",
        help="Type of analysis to run: 'avg', 'min_max', or 'all'.",
    ),
    include_legacy_rounds: bool = typer.Option(
        False,
        "--include-legacy-rounds",
        "-i",
        help="Include legacy rounds in the analysis. Will increase runtime and potentially spam geoguessr with requests, so use sparingly.",
    ),
):
    """Run league analysis tools."""

    if _type in (AnalysisType.AVERAGE_SCORES, AnalysisType.ALL):
        logger.info("Running average scores analysis...")
        asyncio.run(average_scores(include_legacy_rounds=include_legacy_rounds))
    if _type in (AnalysisType.BEST_AND_WORST, AnalysisType.ALL):
        asyncio.run(round_analysis(include_legacy_rounds=include_legacy_rounds))


if __name__ == "__main__":
    app()
