from teleguessr.models import ChallengeResult


def get_ranks_from_scores(
    scores: dict[str, int],
) -> dict[str, int]:
    """Assign ranks to players based on their scores, handling ties appropriately.

    Args:
        scores (dict[str, int]): A dictionary mapping player names to their scores.
    Returns:
        dict[str, int]: A dictionary mapping player names to their rank.
    """
    sorted_players = sorted(scores.items(), key=lambda item: item[1], reverse=True)

    ranks: dict[str, int] = {}
    current_rank = 1
    previous_score = None
    players_with_same_score = 0
    for index, (player, score) in enumerate(sorted_players):
        if score == previous_score:
            players_with_same_score += 1
        else:
            current_rank = index + 1
            players_with_same_score = 1

        ranks[player] = current_rank
        previous_score = score

    return ranks


def get_mid_round_ranks(player: str, round_result: ChallengeResult) -> tuple[int, int]:
    """Get the mid-round ranks for a specific player, as per the number of rounds that player has played so far."""

    net_scores = {}
    gross_scores = {}

    player_score = next(
        (score for score in round_result.scores if score.player.name == player), None
    )

    if player_score is None:
        raise ValueError(f"No score found for {player}")

    rounds_played = player_score.rounds_completed

    for score in round_result.scores:
        gross_scores[score.player.name] = score.compute_partial_gross_score(
            rounds_played
        )
        net_scores[score.player.name] = score.compute_partial_net_score(rounds_played)

    gross_ranks = get_ranks_from_scores(gross_scores)
    net_ranks = get_ranks_from_scores(net_scores)

    return gross_ranks[player], net_ranks[player]
