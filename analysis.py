from collections import defaultdict
from collections.abc import AsyncGenerator
from pprint import pprint
import statistics
from typing import Iterable

import pandas as pd
from awards import rayleigh_scores
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


def get_guess_dataframe(round_result: ChallengeResult) -> pd.DataFrame:
    data = []
    for rs in round_result.scores:
        for i, guess in enumerate(rs.guesses):
            data.append(
                {
                    "player": rs.player.name,
                    "location_index": i + 1,
                    "guess_score": guess.score,
                    "guess_distance_km": guess.distance_km,
                }
            )
    df = pd.DataFrame(data)
    return df

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
        
async def rayleigh_analysis(challenge_ids: list[str]):
    
    data = []
    async for challenge_result in get_results_for_challenges(challenge_ids):

        scores = rayleigh_scores(challenge_result)
        for (player_name, location_index), score in scores.items():
            print(
                f"Player {player_name} - Location {location_index}: Rayleigh Score = {score:.2f}"
            )

            player_guess = challenge_result.get_guess(player_name, location_index - 1)
            data.append({
                "player_name": player_name,
                "location_index": location_index,
                "rayleigh_score": score,
                "guess_distance_km": player_guess.distance_km,
                "guess_score": player_guess.score,
                "challenge_url": challenge_result.challenge_url,
            })
    df = pd.DataFrame(data)
    df.to_csv("data/rayleigh_analysis.csv", index=False)

if __name__ == "__main__":
    import asyncio

    ALL_CHALLENGES = [
        "3qfccXf0H2LxVfKd",
        "GaE9HCgVPNUVAAtD",
        "o6HtQ5XfgdXzY7hO",
        "J2tCBccFnlJq1eUD",
        "X37AfCqv57u8rGdz",
        "qYfz8PCNsvSEcEpo",
        "jnPeVIR9cMMcaHKL",
        "EO15fho3VkzB41CX",
        "bwnTLsC4oVV0zkSY",
        "5zDtniWpKjF9cL8I",
        "DT3pVBmF4MVZt0QS",
        "iOgqSZ2AFXV0k1ku",
        "uLRo3Nl2ZbMG3HnL",
        "8YpJQusdcr2DkNjV",
        "cU0tALpAOGT6iLET",
        "ctNxp7ksqHuKyBWd",
        "nDlRf0Nfg9f19lyR",
        "sgTR0MdmQRJ9Ntdx",
        "OEViUK0CsXsO7BcB",
        "bJMNpBrnnH9tTguW",
    ]

    asyncio.run(rayleigh_analysis(ALL_CHALLENGES))
