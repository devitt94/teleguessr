from collections import defaultdict
from collections.abc import AsyncGenerator

from awards import get_ranked_guesses
from geoguessr_scraper import get_challenge_scores
from formatters import format_scoreboard

import dotenv

from models import ChallengeResult

dotenv.load_dotenv()

CHALLENGE_URLS = [
    "https://www.geoguessr.com/challenge/uRZJEmW32RDdxRme",
    "https://www.geoguessr.com/challenge/Dw1FhWM5GKPxxPhl",
    "https://www.geoguessr.com/challenge/hYq5oMDONO3Jl2Sx",
    "https://www.geoguessr.com/challenge/lKppru0IWyDZwIAW",
    "https://www.geoguessr.com/challenge/i9tEGmao2qB684un",
    "https://www.geoguessr.com/challenge/sh8hlW70FBUHblJo",
    "https://www.geoguessr.com/challenge/HX1zet3ADxT0s1MF",
]


async def average_scores():
    totals = defaultdict(int)
    for url in CHALLENGE_URLS:
        result = await get_challenge_scores(url)
        for player_score in result.scores:
            totals[player_score.player.name] += player_score.gross_score

    averages = {
        player: round(total_score / len(CHALLENGE_URLS))
        for player, total_score in totals.items()
    }
    print(format_scoreboard(averages, header="Average Score"))


async def get_results_for_challenges(
    challenge_ids: list[str],
) -> AsyncGenerator[ChallengeResult]:
    for challenge_id in challenge_ids:
        url = f"https://www.geoguessr.com/challenge/{challenge_id}"
        try:
            result = await get_challenge_scores(url)
            yield result
        except Exception as e:
            print(f"Error fetching challenge {challenge_id}: {e}")
            raise


async def analyse_round(challenge_id: str):
    challenge_url = f"https://www.geoguessr.com/challenge/{challenge_id}"
    result = await get_challenge_scores(challenge_url)
    ranked_guesses = get_ranked_guesses(result)

    table_data = {
        f"{rg.player.name}-{rg.location_index}": rg.adjusted_score
        for rg in ranked_guesses
    }
    print(
        format_scoreboard(
            table_data, header=f"Adjusted Scores for Challenge {challenge_id}"
        )
    )


if __name__ == "__main__":
    import asyncio

    ALL_CHALLENGES = [
        "862qIpnYWI3V07S1",
    ]

    asyncio.run(analyse_round(ALL_CHALLENGES[0]))
