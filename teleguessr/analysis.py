from collections import defaultdict
import json
from pathlib import Path

from teleguessr.geoguessr_scraper import GeoguessrClient

import pandas as pd
import dotenv

from teleguessr.settings import get_settings

dotenv.load_dotenv()

CHALLENGE_URLS = {
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


def get_challange_urls_from_finished_leagues() -> set[str]:
    urls = set()
    for league_file in FINISHED_LEAGUES_DIR.glob("league_*.json"):
        with open(league_file, "r") as f:
            league_data = json.load(f)
        for round_info in league_data["results"]:
            urls.add(round_info["challenge_url"])
    return urls


async def average_scores():
    totals = defaultdict(int)
    rounds_played = defaultdict(int)
    settings = get_settings()
    client = GeoguessrClient(
        ncfa_cookie=settings.geoguessr_ncfa_cookie
    )  # Add valid cookie if needed

    for url in CHALLENGE_URLS.union(get_challange_urls_from_finished_leagues()):
        result = await client.get_challenge_scores(url, {}, 0.0)
        if len(result.scores) < 3:
            print(
                f"Skipping challenge {url} due to insufficient players ({len(result.scores)})"
            )
            continue
        else:
            print(f"Processing challenge {url} with {len(result.scores)} players")
        for player_score in result.scores:
            totals[player_score.player.name] += player_score.gross_score
            rounds_played[player_score.player.name] += 1

    df = pd.DataFrame(
        {
            "average_score": {
                player: totals[player] / rounds_played[player] for player in totals
            },
            "rounds_played": rounds_played,
        }
    )
    df.index.name = "player"
    df["average_score"] = df["average_score"].round(0)
    df.sort_values(by=["average_score"], inplace=True, ascending=False)
    print("Average Scores:")
    print(df)


async def round_analysis():
    data = []
    settings = get_settings()
    client = GeoguessrClient(
        ncfa_cookie=settings.geoguessr_ncfa_cookie
    )  # Add valid cookie if needed

    handicaps = {}
    default_handicap = 0.0
    for url in CHALLENGE_URLS:
        result = await client.get_challenge_scores(url, handicaps, default_handicap)
        print(f"Analyzing results for challenge: {url}")
        for player_score in result.scores:
            data.append(
                {
                    "player": player_score.player.name,
                    "round_id": url.split("/")[-1],
                    "gross_score": player_score.gross_score,
                    "hcap_adjustment": player_score.hcap_adjustment,
                    "net_score": player_score.net_score,
                }
            )

    df = pd.DataFrame(data)

    df.sort_values(by=["gross_score"], inplace=True)

    print("Worst Gross Scores:")
    print(df[["player", "round_id", "gross_score"]].head())

    print("\nBest Gross Scores:")
    print(df[["player", "round_id", "gross_score"]].tail().iloc[::-1])


if __name__ == "__main__":
    import asyncio

    asyncio.run(average_scores())
