import json
from pathlib import Path

from teleguessr.awards import get_ranked_guesses
from teleguessr.formatters import format_leaderboard_html
from teleguessr.geoguessr_scraper import GeoguessrClient
from teleguessr.handicaps import calculate_new_handicaps
from teleguessr.league import LeagueState
from teleguessr.ranks import get_ranks_from_scores
from teleguessr.settings import LeagueSettings


async def replay_league(
    league_path: Path,
    handicaps: dict[str, float],
    league_settings: LeagueSettings,
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
            default_handicap=league_settings.default_handicap_multiplier,
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

    if handicaps:
        print("\n\n")
        print("Handicap adjustments after replay:")

        # Calculate and update handicaps
        player_ranks = get_ranks_from_scores(
            league_state.get_leaderboard_data()["scores"]
        )
        new_handicaps = calculate_new_handicaps(player_ranks, league_settings)

        for player, new_handicap in new_handicaps.items():
            old_handicap = handicaps.get(
                player, league_settings.default_handicap_multiplier
            )
            print(f"{player}: {old_handicap:.0%} -> {new_handicap:.0%}")


if __name__ == "__main__":
    import asyncio
    from teleguessr.settings import get_settings

    league_id = 5

    settings = get_settings()
    league_file = (
        settings.data_dir / "leagues" / "finished" / f"league_{league_id}.json"
    )

    include_handicaps = True

    if include_handicaps:
        handicaps_file = (
            settings.data_dir / "handicaps" / f"handicaps_league_{league_id}.json"
        )
        with open(handicaps_file, "r") as f:
            handicaps = json.load(f)

    else:
        handicaps = {}
        settings.league.default_handicap_multiplier = 0.0

    asyncio.run(
        replay_league(
            league_path=league_file,
            handicaps=handicaps,
            league_settings=settings.league,
            geoguessr_cookie=settings.geoguessr_ncfa_cookie,
        )
    )
