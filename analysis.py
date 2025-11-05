from collections import defaultdict
from pprint import pprint
import statistics
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


async def awards_analysis():
    # for url in CHALLENGE_URLS:
    for url in ["https://www.geoguessr.com/challenge/q1jl07AoTdu9XqVr"]:
        result = await get_challenge_scores(url)

        all_guesses = []

        for round_score in result.scores:
            for i, guess in enumerate(round_score.guesses):
                # Exclude current score from stats calculation
                other_guesses = [
                    rs.guesses[i].score
                    for rs in result.scores
                    if rs.player.name != round_score.player.name
                ]

                other_guess_avg = statistics.mean(other_guesses)
                other_guess_stddev = (
                    statistics.stdev(other_guesses) if len(other_guesses) > 1 else 0.0
                )

                z_score = (
                    (guess.score - other_guess_avg) / other_guess_stddev
                    if other_guess_stddev
                    else 0
                )

                all_guesses.append(
                    {
                        "player": round_score.player.name,
                        "guess": guess.score,
                        "z_score": z_score,
                        "location_index": i + 1,
                        "avg": other_guess_avg,
                        "stddev": other_guess_stddev,
                    }
                )

            print()

        all_guesses.sort(key=lambda x: x["z_score"], reverse=True)

        pprint(all_guesses)


if __name__ == "__main__":
    import asyncio

    asyncio.run(awards_analysis())
