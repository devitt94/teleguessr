import json
from pathlib import Path

from teleguessr.awards import get_ranked_guesses
from teleguessr.league import LeagueState
from teleguessr.models import ChallengeResult
from teleguessr.settings import LeagueSettings


def apply_handicaps_to_challenge_result(
    challenge_result: ChallengeResult,
    handicaps: dict[str, float],
) -> ChallengeResult:
    for score in challenge_result.scores:
        if score.player.name in handicaps:
            score.player.hcap_multiplier = handicaps[score.player.name]
        else:
            score.player.hcap_multiplier = 0.0
    return challenge_result


async def replay_league(
    league_path: Path,
    handicaps: dict[str, float],
    league_settings: LeagueSettings,
) -> LeagueState:
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
        league_state.start_round("Replayed League", -1, round_result.challenge_settings)

        round_result = apply_handicaps_to_challenge_result(round_result, handicaps)
        ranked_guesses = get_ranked_guesses(round_result)

        league_state.add_round_result(round_result)
        league_state.add_awards(ranked_guesses[0], ranked_guesses[-1])
        league_state.save()

    return league_state
