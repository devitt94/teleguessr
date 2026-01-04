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
