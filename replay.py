import json
from pathlib import Path

from awards import get_ranked_guesses
from formatters import format_leaderboard_html
from geoguessr_scraper import GeoguessrClient
from league import LeagueState


async def replay_league(
    league_path: Path,
    handicaps: dict[str, float],
    default_handicap: float,
    geoguessr_cookie: str,
):
    with open(league_path, "r") as f:
        league_data = json.load(f)

    replayed_league_path: Path = league_path.parent / f"replayed_{league_path.name}"
    replayed_league_path.unlink(missing_ok=True)

    challenge_urls = [
        round_info["challenge_url"] for round_info in league_data["results"]
    ]
    client = GeoguessrClient(ncfa_cookie=geoguessr_cookie)

    league_state = LeagueState(
        num_rounds=len(challenge_urls),
        filepath=replayed_league_path,
    )

    for i, url in enumerate(challenge_urls, start=1):
        league_state.start_round("Replayed League", 0)
        print(f"Replaying round {i}/{len(challenge_urls)}: {url}")
        round_result = await client.get_challenge_scores(
            url,
            handicaps=handicaps,
            default_handicap=default_handicap,
        )

        ranked_guesses = get_ranked_guesses(round_result)

        league_state.add_round_result(round_result)
        league_state.add_awards(ranked_guesses[0], ranked_guesses[-1])
        league_state.save()
        print("Round replayed and saved.\n")
        print("Current Leaderboard:")
        print(format_leaderboard_html(**league_state.get_leaderboard_data()))

    leaderboard = league_state.get_leaderboard_data()
    leaderboard_text = format_leaderboard_html(**leaderboard)
    print("Final Leaderboard after replay:")
    print(leaderboard_text.replace("<b>", "").replace("</b>", ""))


if __name__ == "__main__":
    import asyncio
    from settings import get_settings

    settings = get_settings()
    league_file = settings.data_dir / "leagues" / "finished" / "league_2.json"

    asyncio.run(
        replay_league(
            league_path=league_file,
            handicaps={},
            default_handicap=0.0,
            geoguessr_cookie=settings.geoguessr_ncfa_cookie,
        )
    )
