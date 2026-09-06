#!/usr/bin/env python3

import asyncio
import datetime
from enum import Enum
import json

from loguru import logger

from teleguessr import formatters
from teleguessr.active_players import PlayerManager
from teleguessr.formatters import format_leaderboard_html
from teleguessr.geoguessr_scraper import GeoguessrClient
from teleguessr.other_handlers.gross_handler import build_gross_stats_handler
from teleguessr.handicaps import calculate_new_handicaps, get_latest_handicaps
from teleguessr.league import get_last_finished_league_date
from teleguessr.odds import FractionalOdds
from teleguessr.other_handlers.player_handler import (
    PLAYER_STATS_CALLBACK_PREFIX,
    build_player_callback_handler,
    build_player_command_handler,
)
from teleguessr.ranks import get_ranks_from_scores
from teleguessr.replay import replay_league
from teleguessr.settings import AppSettings, get_settings
from teleguessr.bot_manager import (
    BET_SELECT_AMOUNT,
    BET_SELECT_BET_TYPE,
    BET_SELECT_PLAYER,
    OPT_IN_CALLBACK,
    BotManager,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
)
from telegram.request import HTTPXRequest
import typer


async def initlise_bot_manager(
    settings: AppSettings, test_mode: bool = False
) -> BotManager:
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    geoguessr_client = GeoguessrClient(ncfa_cookie=settings.geoguessr_ncfa_cookie)
    handicaps = get_latest_handicaps(settings.league)
    player_manager = PlayerManager(
        data_dir=settings.data_dir, initial_players=set(handicaps.keys())
    )

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
        model_settings=settings.model,
        geoguessr_client=geoguessr_client,
        player_manager=player_manager,
    )
    await bot_manager.initialise()
    return bot_manager


async def post_init(application: Application) -> None:
    commands = [
        ("status", "Display the current status of the round"),
        ("handicaps", "Display the current player handicaps"),
        ("lounge", "Join the players lounge after your round"),
        ("odds", "Display current odds."),
        ("position", "Display your current betting position"),
        ("bet", "Place a bet"),
        ("exposure", "Display DevBet's position"),
        ("outcomes", "Display all betting outcomes"),
        ("records", "Display all-time records"),
        ("rankscores", "Display the points awarded for each rank in a round"),
        ("livescores", "Display the live leaderboard for a round."),
        ("guesses", "Display the ranked guesses for the current round."),
    ]

    await application.bot.set_my_commands(commands)


def main(test_mode: bool = False):
    settings = get_settings()

    settings.data_dir.mkdir(parents=True, exist_ok=True)

    bot_manager = asyncio.run(initlise_bot_manager(settings, test_mode))
    logger.info("BotManager initialised.")

    bet_handler = ConversationHandler(
        entry_points=[CommandHandler("bet", bot_manager.start_bet)],
        states={
            BET_SELECT_PLAYER: [
                CallbackQueryHandler(bot_manager.handle_player_selection),
                CallbackQueryHandler(bot_manager.cancel_bet, pattern="^cancel$"),
            ],
            BET_SELECT_BET_TYPE: [
                CallbackQueryHandler(bot_manager.handle_bet_type_selection),
                CallbackQueryHandler(bot_manager.cancel_bet, pattern="^cancel$"),
            ],
            BET_SELECT_AMOUNT: [
                CallbackQueryHandler(bot_manager.handle_amount_selection),
                CallbackQueryHandler(bot_manager.cancel_bet, pattern="^cancel$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", bot_manager.cancel_bet)],
    )

    request = HTTPXRequest(
        read_timeout=30, write_timeout=30, connect_timeout=10, pool_timeout=10
    )

    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .request(request)
        .build()
    )
    app.add_handler(CommandHandler("help", bot_manager.help_handler))
    app.add_handler(CommandHandler("startleague", bot_manager.start_league_handler))
    app.add_handler(CommandHandler("leaderboard", bot_manager.leaderboard_handler))
    app.add_handler(CommandHandler("endround", bot_manager.end_round_handler))
    app.add_handler(CommandHandler("handicaps", bot_manager.handicaps_handler))
    app.add_handler(CommandHandler("status", bot_manager.status_handler))
    app.add_handler(CommandHandler("lounge", bot_manager.lounge_handler))
    app.add_handler(CommandHandler("odds", bot_manager.odds_handler))
    app.add_handler(CommandHandler("position", bot_manager.position_handler))
    app.add_handler(CommandHandler("exposure", bot_manager.exposure_handler))
    app.add_handler(CommandHandler("guesses", bot_manager.guesses_handler))
    app.add_handler(CommandHandler("outcomes", bot_manager.outcomes_handler))
    app.add_handler(CommandHandler("records", bot_manager.records_handler))
    app.add_handler(CommandHandler("rankscores", bot_manager.rank_scores_handler))
    app.add_handler(CommandHandler("livescores", bot_manager.live_scoring_handler))
    app.add_handler(
        CommandHandler("scoresneeded", bot_manager.gross_scores_needed_handler)
    )
    app.add_handler(
        CommandHandler("gross", build_gross_stats_handler(settings.data_dir))
    )
    app.add_handler(
        CommandHandler("player", build_player_command_handler(settings.data_dir))
    )
    app.add_handler(CommandHandler("suspend", bot_manager.suspend_handler))
    app.add_handler(CommandHandler("unsuspend", bot_manager.unsuspend_handler))
    app.add_handler(
        CallbackQueryHandler(bot_manager.handle_opt_in, pattern=f"^{OPT_IN_CALLBACK}$")
    )
    app.add_handler(
        CallbackQueryHandler(
            build_player_callback_handler(settings.data_dir),
            pattern=f"^{PLAYER_STATS_CALLBACK_PREFIX}",
        )
    )
    app.add_handler(bet_handler)
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
    league_date: str = typer.Option(
        None,
        "--league-date",
        "-l",
        help="Date of the league to replay in YYYYMMDD format. Defaults to the latest finished league.",
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
    if league_date is None:
        league_date = get_last_finished_league_date(finished_league_dir)
    else:
        league_date = datetime.datetime.strptime(league_date, "%Y%m%d").date()

    league_file = finished_league_dir / f"league_{league_date.strftime('%Y%m%d')}.json"

    if not league_file.exists():
        logger.error(f"League file {league_file} does not exist.")
        return

    handicaps_file = (
        settings.data_dir
        / "handicaps"
        / f"handicaps_league_{league_date.strftime('%Y%m%d')}.json"
    )
    with open(handicaps_file, "r") as f:
        handicaps = json.load(f)

    if not include_handicaps:
        handicaps = {player: 0.0 for player in handicaps.keys()}

    league_state = asyncio.run(
        replay_league(
            league_path=league_file,
            handicaps=handicaps,
            league_settings=settings.league,
        )
    )

    leaderboard = league_state.get_leaderboard_data()
    leaderboard_text = format_leaderboard_html(**leaderboard)
    print("Final Leaderboard after replay:")
    print(leaderboard_text.replace("<b>", "").replace("</b>", ""))

    if include_handicaps:
        print("\n\n")
        print("Handicap adjustments after replay:")

        # Calculate and update handicaps
        player_ranks = get_ranks_from_scores(
            league_state.get_leaderboard_data()["scores"]
        )
        new_handicaps = calculate_new_handicaps(player_ranks, settings.league)

        for player, new_handicap in new_handicaps.items():
            old_handicap = handicaps.get(
                player, settings.league.default_handicap_multiplier
            )
            print(f"{player}: {old_handicap:.0%} -> {new_handicap:.0%}")


class AnalysisType(str, Enum):
    AVERAGE_SCORES = "avg"
    BEST_AND_WORST = "min_max"
    HANDICAPS = "handicaps"
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
    try:
        from teleguessr.analysis import (
            average_scores,
            handicap_analysis,
            round_analysis,
        )
    except ImportError:
        logger.warning(
            "Analysis packages are not installed. Please install them with 'pip install teleguessr[analysis]'."
        )
        return

    if _type in (AnalysisType.AVERAGE_SCORES, AnalysisType.ALL):
        logger.info("Running average scores analysis...")
        asyncio.run(average_scores(include_legacy_rounds=include_legacy_rounds))
    if _type in (AnalysisType.BEST_AND_WORST, AnalysisType.ALL):
        asyncio.run(round_analysis(include_legacy_rounds=include_legacy_rounds))

    if _type in (AnalysisType.HANDICAPS, AnalysisType.ALL):
        logger.info("Analysing handicaps...")
        asyncio.run(handicap_analysis(include_legacy_rounds=include_legacy_rounds))


@app.command()
def predictions(
    include_legacy_rounds: bool = typer.Option(
        False,
        "--include-legacy-rounds",
        "-i",
        help="Include legacy rounds in the predictions. Will increase runtime and potentially spam geoguessr with requests, so use sparingly.",
    ),
    n_sims: int = typer.Option(
        40_000,
        "--n-sims",
        "-n",
        help="Number of simulations to run for the predictions. Higher numbers will increase accuracy but also increase runtime. Default is 40,000.",
    ),
):
    """Generate outright odds predictions for the current league."""
    from teleguessr.predictions import generate_outright_odds_predictions

    player_manager = PlayerManager(
        data_dir=get_settings().data_dir,
        initial_players=set(get_latest_handicaps(get_settings().league).keys()),
    )
    preds = asyncio.run(
        generate_outright_odds_predictions(
            n_sims=n_sims,
            runners=player_manager.get_active_players(),
            include_legacy_rounds=include_legacy_rounds,
        )
    )
    print(preds)
    print("\n\n")
    back_odds = dict(
        zip(
            preds["player"],
            (
                FractionalOdds.from_str(odds)
                for odds in preds["back_win_odds"]
                if odds is not None
            ),
        )
    )
    lay_odds = dict(
        zip(
            preds["player"],
            (
                FractionalOdds.from_str(odds)
                for odds in preds["lay_win_odds"]
                if odds is not None
            ),
        )
    )
    print("Predicted outright odds:")
    print(json.dumps(dict(zip(preds["player"], preds["back_win_odds"])), indent=4))
    print("\n\n")
    print("Predicted lay odds:")
    print(json.dumps(dict(zip(preds["player"], preds["lay_win_odds"])), indent=4))
    print("\n\n")
    print(formatters.format_odds_message(back_odds, lay_odds))


if __name__ == "__main__":
    app()
