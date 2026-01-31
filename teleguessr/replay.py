import json
from pathlib import Path

from teleguessr.awards import get_ranked_guesses
from teleguessr.formatters import format_leaderboard_html
from teleguessr.handicaps import calculate_new_handicaps
from teleguessr.league import LeagueState
from teleguessr.models import ChallengeResult
from teleguessr.ranks import get_ranks_from_scores
from teleguessr.settings import LeagueSettings


def apply_handicaps_to_challenge_result(
    challenge_result: ChallengeResult,
    handicaps: dict[str, float],
) -> ChallengeResult:
    for score in challenge_result.scores:
        if score.player.name in handicaps:
            score.player.hcap_multiplier = handicaps[score.player.name]
    return challenge_result


async def replay_league(
    league_path: Path,
    handicaps: dict[str, float],
    league_settings: LeagueSettings,
    show_handicap_adjustments: bool = False,
):
    with open(league_path, "r") as f:
        league_data = json.load(f)

    replayed_league_path: Path = league_path.parent / f"replayed_{league_path.name}"
    replayed_league_path.unlink(missing_ok=True)

    league_state = LeagueState(
        num_rounds=league_settings.number_of_rounds,
        filepath=replayed_league_path,
    )

    round_results = [ChallengeResult(**rr) for rr in league_data["results"]]

    for round_result in round_results:
        league_state.start_round("Replayed League", -1)

        round_result = apply_handicaps_to_challenge_result(round_result, handicaps)
        ranked_guesses = get_ranked_guesses(round_result)

        league_state.add_round_result(round_result)
        league_state.add_awards(ranked_guesses[0], ranked_guesses[-1])
        league_state.save()

    leaderboard = league_state.get_leaderboard_data()
    leaderboard_text = format_leaderboard_html(**leaderboard)
    print("Final Leaderboard after replay:")
    print(leaderboard_text.replace("<b>", "").replace("</b>", ""))

    if show_handicap_adjustments:
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
