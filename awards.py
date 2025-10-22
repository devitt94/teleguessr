import statistics
from models import Award, Awards, RoundResult, GuessStats


def compute_stats(round_result: RoundResult) -> list[GuessStats]:
    """
    Compute average and standard deviation of guess distances for each guess index.
    Returns a list of GuessStats objects, one for each guess index.
    """

    num_guesses = len(round_result.scores[0].guesses)
    all_distances: list[list[float]] = [[] for _ in range(num_guesses)]

    for round_score in round_result.scores:
        for i, guess in enumerate(round_score.guesses):
            all_distances[i].append(guess.distance_km)

    stats: list[GuessStats] = []
    for distances in all_distances:
        avg = statistics.mean(distances)
        stddev = statistics.stdev(distances) if len(distances) > 1 else 0.0
        stats.append(GuessStats(average=avg, stddev=stddev))

    return stats


def get_best_and_worst_guesses(round_result: RoundResult) -> Awards:
    """
    Return the player name and Guess object for the worst guess by z-score.

    """
    best_player = ""
    best_guess_obj = None
    best_z_score = float("inf")

    worst_player = ""
    worst_guess_obj = None
    worst_z_score = float("-inf")

    all_guess_stats = compute_stats(round_result)

    for round_score in round_result.scores:
        for i, guess in enumerate(round_score.guesses):
            guess_stats = all_guess_stats[i]
            if guess_stats.stddev == 0:
                z_score = 0.0
            else:
                z_score = (guess.distance_km - guess_stats.average) / guess_stats.stddev

            if z_score < best_z_score:
                best_z_score = z_score
                best_player = round_score.player
                best_guess_obj = guess
                best_guess_stats = guess_stats
                round_index = i + 1

            if z_score > worst_z_score:
                worst_z_score = z_score
                worst_player = round_score.player
                worst_guess_obj = guess
                worst_guess_stats = guess_stats
                worst_round_index = i + 1

    return Awards(
        best_guess=Award(
            player=best_player,
            guess=best_guess_obj,
            round_stats=best_guess_stats,
            location_index=round_index,
        ),
        worst_guess=Award(
            player=worst_player,
            guess=worst_guess_obj,
            round_stats=worst_guess_stats,
            location_index=worst_round_index,
        ),
    )
