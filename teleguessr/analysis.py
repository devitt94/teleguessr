import json
from pathlib import Path

from loguru import logger

from teleguessr.geoguessr_scraper import GeoguessrClient

import dotenv

from teleguessr.models import ChallengeResult
from teleguessr.settings import get_settings

dotenv.load_dotenv()

LEGACY_CHALLENGE_URLS = {
    # Legacy challenge URLs from previous leagues before recording was automated
    "https://www.geoguessr.com/challenge/3qfccXf0H2LxVfKd",
    "https://www.geoguessr.com/challenge/5zDtniWpKjF9cL8I",
    "https://www.geoguessr.com/challenge/862qIpnYWI3V07S1",
    "https://www.geoguessr.com/challenge/8YpJQusdcr2DkNjV",
    "https://www.geoguessr.com/challenge/92KcQzZWwNGfb0eB",
    "https://www.geoguessr.com/challenge/989O8zGW1iWsfrsu",
    "https://www.geoguessr.com/challenge/ALvkMtCyioXjXJfj",
    "https://www.geoguessr.com/challenge/DT3pVBmF4MVZt0QS",
    "https://www.geoguessr.com/challenge/EO15fho3VkzB41CX",
    "https://www.geoguessr.com/challenge/GaE9HCgVPNUVAAtD",
    "https://www.geoguessr.com/challenge/HhBflrIkGTGPr1uo",
    "https://www.geoguessr.com/challenge/J2tCBccFnlJq1eUD",
    "https://www.geoguessr.com/challenge/KGI2gHP15ejmDGVg",
    "https://www.geoguessr.com/challenge/OEViUK0CsXsO7BcB",
    "https://www.geoguessr.com/challenge/Rszuuy3Erzra0VVs",
    "https://www.geoguessr.com/challenge/TBoioOIrdqrFZJIQ",
    "https://www.geoguessr.com/challenge/Wl7VfeHU0W6R7Eu3",
    "https://www.geoguessr.com/challenge/X37AfCqv57u8rGdz",
    "https://www.geoguessr.com/challenge/b1xLYaAyVSEmR8t9",
    "https://www.geoguessr.com/challenge/bJMNpBrnnH9tTguW",
    "https://www.geoguessr.com/challenge/cU0tALpAOGT6iLET",
    "https://www.geoguessr.com/challenge/ctNxp7ksqHuKyBWd",
    "https://www.geoguessr.com/challenge/gVmY1NVOqnaHnHy4",
    "https://www.geoguessr.com/challenge/iOgqSZ2AFXV0k1ku",
    "https://www.geoguessr.com/challenge/jnPeVIR9cMMcaHKL",
    "https://www.geoguessr.com/challenge/nDlRf0Nfg9f19lyR",
    "https://www.geoguessr.com/challenge/o6HtQ5XfgdXzY7hO",
    "https://www.geoguessr.com/challenge/p3gCJv07XI8WhI2I",
    "https://www.geoguessr.com/challenge/q1jl07AoTdu9XqVr",
    "https://www.geoguessr.com/challenge/qYfz8PCNsvSEcEpo",
    "https://www.geoguessr.com/challenge/rRE1qeaeU7butj9q",
    "https://www.geoguessr.com/challenge/sGBNv6Sy0axvixlc",
    "https://www.geoguessr.com/challenge/sgTR0MdmQRJ9Ntdx",
    "https://www.geoguessr.com/challenge/svZKlxHTVebzd1m8",
    "https://www.geoguessr.com/challenge/uLRo3Nl2ZbMG3HnL",
}

FINISHED_LEAGUES_DIR = Path("data/leagues/finished/")


def get_challenge_results_from_finished_leagues() -> list[ChallengeResult]:
    results = []
    for league_file in FINISHED_LEAGUES_DIR.glob("league_*.json"):
        with open(league_file, "r") as f:
            league_data = json.load(f)
        for round_info in league_data["results"]:
            results.append(ChallengeResult(**round_info))

    return results


async def get_legacy_challenge_results(
    geoguessr_client: GeoguessrClient,
) -> list[ChallengeResult]:
    results = []
    for challenge_url in LEGACY_CHALLENGE_URLS:
        result = await geoguessr_client.get_challenge_scores(challenge_url, {}, 0.0)
        results.append(result)

    return results


async def get_all_challenge_results(
    include_legacy_rounds: bool = False,
) -> list[ChallengeResult]:
    results = get_challenge_results_from_finished_leagues()
    if include_legacy_rounds:
        logger.info("Including legacy rounds in analysis...")
        settings = get_settings()
        client = GeoguessrClient(
            ncfa_cookie=settings.geoguessr_ncfa_cookie
        )  # Add valid cookie if needed
        legacy_results = await get_legacy_challenge_results(client)
        results.extend(legacy_results)

    return results


async def average_scores(include_legacy_rounds: bool = False):
    results = await get_all_challenge_results(include_legacy_rounds)

    data = []
    for round_result in results:
        if len(round_result.scores) < 3:
            logger.info(
                f"Skipping challenge {round_result.url} due to insufficient players ({len(round_result.scores)})"
            )
            continue

        for player_score in round_result.scores:
            data.append(
                {
                    "player": player_score.player.name,
                    "gross_score": player_score.gross_score,
                }
            )

    logger.info("Average Scores:")
    player_totals = {}
    player_counts = {}
    for entry in data:
        player = entry["player"]
        score = entry["gross_score"]
        if player not in player_totals:
            player_totals[player] = 0
            player_counts[player] = 0
        player_totals[player] += score
        player_counts[player] += 1

    player_average_count_triples = [
        (player, player_totals[player] / player_counts[player], player_counts[player])
        for player in player_totals
    ]

    player_average_count_triples.sort(key=lambda x: x[1], reverse=True)
    for player, average_score, count in player_average_count_triples:
        logger.info(f"{player}: {average_score:.2f} (played {count} rounds)")


async def round_analysis(
    include_legacy_rounds: bool = False,
):
    data = []

    for result in await get_all_challenge_results(include_legacy_rounds):
        url = result.challenge_url
        for player_score in result.scores:
            data.append(
                {
                    "player": player_score.player.name,
                    "round_id": url.split("/")[-1],
                    "gross_score": player_score.gross_score,
                }
            )

    logger.info("Top 5 Gross Scores:")
    sorted_by_gross = sorted(data, key=lambda x: x["gross_score"], reverse=True)
    for entry in sorted_by_gross[:5]:
        logger.info(
            f"{entry['player']} - Round {entry['round_id']}: Gross Score = {entry['gross_score']}"
        )

    logger.info("Bottom 5 Gross Scores:")
    for entry in sorted_by_gross[-5::-1]:
        logger.info(
            f"{entry['player']} - Round {entry['round_id']}: Gross Score = {entry['gross_score']}"
        )
