import asyncio
import random

from loguru import logger
from geoguessr_scraper import GeoguessrClient
from settings import AppSettings, get_settings
from bot_manager import BotManager
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
)


async def initlise_bot_manager(
    settings: AppSettings, test_mode: bool = False
) -> BotManager:
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    geoguessr_client = GeoguessrClient(ncfa_cookie=settings.geoguessr_ncfa_cookie)

    if test_mode:
        geoguessr_client.create_challenge = create_fake_challenge
        settings.league.time_per_round_hours = 0.02  # 7.2 seconds

    bot_manager = BotManager(
        admin_id=settings.telegram_admin_id,
        data_dir=settings.data_dir,
        league_settings=settings.league,
        geoguessr_client=geoguessr_client,
    )
    await bot_manager.initialise()
    return bot_manager


async def create_fake_challenge(
    map_id: str,
    time_limit_seconds: int,
) -> str:
    """Create a fake challenge URL for testing purposes."""

    challenge_urls = [
        "https://www.geoguessr.com/challenge/X37AfCqv57u8rGdz",
        "https://www.geoguessr.com/challenge/J2tCBccFnlJq1eUD",
        "https://www.geoguessr.com/challenge/gVmY1NVOqnaHnHy4",
        "https://www.geoguessr.com/challenge/KGI2gHP15ejmDGVg",
        "https://www.geoguessr.com/challenge/989O8zGW1iWsfrsu",
    ]

    return random.choice(challenge_urls)


def main(test_mode: bool = False):
    settings = get_settings()

    settings.data_dir.mkdir(parents=True, exist_ok=True)

    bot_manager = asyncio.run(initlise_bot_manager(settings, test_mode))
    logger.info("BotManager initialised.")

    app = ApplicationBuilder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("startleague", bot_manager.start_league_handler))
    app.add_handler(CommandHandler("endround", bot_manager.end_round_handler))
    app.add_handler(CommandHandler("remind", bot_manager.remind_handler))
    app.add_handler(CommandHandler("status", bot_manager.status_handler))
    app.add_handler(CommandHandler("leaderboard", bot_manager.show_leaderboard_handler))
    app.add_handler(
        CommandHandler(
            "currentroundscores", bot_manager.show_current_round_scores_handler
        )
    )
    app.add_error_handler(bot_manager.error_handler)
    logger.info("Bot running...")

    asyncio.run(bot_manager.resume_league_tasks(app))

    app.run_polling()

    logger.info("Bot stopped.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Teleguessr Bot")
    parser.add_argument(
        "--test",
        action="store_true",
        default=False,
        help="Run the bot in test mode.",
    )
    args = parser.parse_args()
    main(test_mode=args.test)
