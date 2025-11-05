import statistics
from models import Award, Awards, Guess, RoundResult, GuessStats


def compute_stats(round_result: RoundResult) -> list[GuessStats]:
    """
    Compute average and standard deviation of guess distances for each guess index.
    Returns a list of GuessStats objects, one for each guess index.
    """

    num_guesses = len(round_result.scores[0].guesses)
    all_distances: list[list[float]] = [[] for _ in range(num_guesses)]
    all_points: list[list[int]] = [[] for _ in range(num_guesses)]

    for round_score in round_result.scores:
        for i, guess in enumerate(round_score.guesses):
            all_distances[i].append(guess.distance_km)
            all_points[i].append(guess.score)

    stats: list[GuessStats] = []
    for distances, points in zip(all_distances, all_points):
        avg_dist = statistics.mean(distances)
        stddev_dist = statistics.stdev(distances) if len(distances) > 1 else 0.0
        avg_pts = statistics.mean(points)
        stddev_pts = statistics.stdev(points) if len(points) > 1 else 0.0
        stats.append(
            GuessStats(
                average_distance=avg_dist,
                stddev_distance=stddev_dist,
                average_pts=avg_pts,
                stddev_pts=stddev_pts,
            )
        )

    return stats


def get_best_and_worst_guesses(
    round_result: RoundResult, by_distance: bool = False
) -> Awards:
    """
    Identify the best and worst guesses in a round based on z-scores.
    Returns an Awards object containing the best and worst guesses.
    """
    best_player = ""
    best_guess_obj = None
    best_z_score = float("-inf")

    worst_player = ""
    worst_guess_obj = None
    worst_z_score = float("inf")

    if by_distance:
        # Lower distance is better, so we invert the z-score calculation
        def compute_z_score(guess: Guess, stats: GuessStats) -> float:
            if stats.stddev_distance == 0:
                return 0.0
            return (stats.average_distance - guess.distance_km) / stats.stddev_distance

    else:

        def compute_z_score(guess: Guess, stats: GuessStats) -> float:
            if stats.stddev_pts == 0:
                return 0.0
            return (guess.score - stats.average_pts) / stats.stddev_pts

    all_guess_stats = compute_stats(round_result)

    for round_score in round_result.scores:
        for i, guess in enumerate(round_score.guesses):
            guess_stats = all_guess_stats[i]
            z_score = compute_z_score(guess, guess_stats)
            if z_score > best_z_score:
                best_z_score = z_score
                best_player = round_score.player
                best_guess_obj = guess
                best_guess_stats = guess_stats
                best_guess_round_index = i + 1

            if z_score < worst_z_score:
                worst_z_score = z_score
                worst_player = round_score.player
                worst_guess_obj = guess
                worst_guess_stats = guess_stats
                worst_guess_round_index = i + 1

    return Awards(
        best_guess=Award(
            player=best_player,
            guess=best_guess_obj,
            round_stats=best_guess_stats,
            location_index=best_guess_round_index,
        ),
        worst_guess=Award(
            player=worst_player,
            guess=worst_guess_obj,
            round_stats=worst_guess_stats,
            location_index=worst_guess_round_index,
        ),
    )
