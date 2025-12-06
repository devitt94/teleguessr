from collections import defaultdict
from collections.abc import AsyncGenerator
from pprint import pprint
import statistics
from typing import Iterable

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


async def awards_analysis(
    challege_ids: list[str],
):
    # for url in CHALLENGE_URLS:
    dataframes = []
    for challenge_id in challege_ids:
        url = f"https://www.geoguessr.com/challenge/{challenge_id}"
        print(f"Fetching challenge {challenge_id}...")
        try:
            result = await get_challenge_scores(url)
        except Exception as e:
            print(f"Error fetching challenge {challenge_id}: {e}")
            raise

        if len(result.scores) == 1:
            print(f"Skipping challenge {challenge_id} with only one player.")
            continue

        df = get_guess_dataframe(result)
        df["challenge_id"] = challenge_id
        df["num_players"] = len(result.scores)
        dataframes.append(df)

    df = pd.concat(dataframes)

    df["round_average_distance"] = df.groupby(["challenge_id", "location_index"])["guess_distance_km"].transform(
        "mean"
    )
    df["round_average_score"] = df.groupby(["challenge_id", "location_index"])["guess_score"].transform(
        "mean"
    )
    df["round_median_distance"] = df.groupby(["challenge_id", "location_index"])["guess_distance_km"].transform(
        "median"
    )
    df["round_median_score"] = df.groupby(["challenge_id", "location_index"])["guess_score"].transform(
        "median"
    )
    df["round_stddev_distance"] = df.groupby(["challenge_id", "location_index"])["guess_distance_km"].transform(
        "std"
    )
    df["round_stddev_score"] = df.groupby(["challenge_id", "location_index"])["guess_score"].transform(
        "std"
    )

    df["distance_zscore"] = df.groupby(["challenge_id", "location_index"])["guess_distance_km"].transform(
        lambda x: (x.mean() - x) / x.std(ddof=0)
    )
    df["score_zscore"] = df.groupby(["challenge_id", "location_index"])["guess_score"].transform(
        lambda x: (x - x.mean()) / x.std(ddof=0)
    )

    df["score_absscore"] = df.groupby(["challenge_id", "location_index"])["guess_score"].transform(
        lambda x: (x - x.mean())
    )

    df["distance_absscore"] = df.groupby(["challenge_id", "location_index"])["guess_distance_km"].transform(
        lambda x: (x.mean() - x)
    )

    df["distance_pctscore"] = df.groupby(["challenge_id", "location_index"])["guess_distance_km"].transform(
        lambda x: 1 -x / x.sum()
    )

    df["score_pctscore"] = df.groupby(["challenge_id", "location_index"])["guess_score"].transform(
        lambda x: x / x.sum()
    )

    df["score_meddiffscore"] = df.groupby(["challenge_id", "location_index"])["guess_score"].transform(
        lambda x: x - x.median()
    )
    df["distance_meddiffscore"] = df.groupby(["challenge_id", "location_index"])["guess_distance_km"].transform(
        lambda x: x.median() - x
    )

    df.to_csv("data/awards_analysis.csv", index=False)


async def get_results_for_challenges(
    challenge_ids: list[str],
) -> AsyncGenerator[ChallengeResult]:
    for challenge_id in challenge_ids:
        url = f"https://www.geoguessr.com/challenge/{challenge_id}"
        print(f"Fetching challenge {challenge_id}...")
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
    print(format_scoreboard(
        table_data,
        header=f"Adjusted Scores for Challenge {challenge_id}"
    ))

if __name__ == "__main__":
    import asyncio

    ALL_CHALLENGES = [
        "862qIpnYWI3V07S1",
    ]

    asyncio.run(analyse_round(ALL_CHALLENGES[0]))
