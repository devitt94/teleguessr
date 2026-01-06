import asyncio
import json

from loguru import logger
from teleguessr.geoguessr_scraper import GeoguessrClient
from teleguessr.settings import AppSettings, get_settings
from teleguessr.bot_manager import BotManager
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
        settings.league.time_per_round_hours = 0.002  # 7.2 seconds

    bot_manager = BotManager(
        admin_id=settings.telegram_admin_id,
        data_dir=settings.data_dir,
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
    app.add_handler(CommandHandler("remind", bot_manager.remind_handler))
    app.add_handler(CommandHandler("status", bot_manager.status_handler))
    app.add_handler(CommandHandler("leaderboard", bot_manager.show_leaderboard_handler))
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
