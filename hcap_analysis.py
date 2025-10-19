from collections import defaultdict
from geoguessr_scraper import get_challenge_scores
from formatters import format_scoreboard

import dotenv

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


async def main():
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


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
