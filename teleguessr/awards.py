import statistics
from typing import Callable
from teleguessr.models import Guess, ChallengeResult, GuessStats, RankedGuess


def compute_stats(round_result: ChallengeResult) -> list[GuessStats]:
    """
    Compute average and standard deviation of guess distances for each guess index.
    Returns a list of GuessStats objects, one for each guess index.
    """

    num_guesses = round_result.num_rounds
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
        second_best_pts = sorted(points, reverse=True)[1] if len(points) > 1 else 0
        second_worst_pts = sorted(points)[1] if len(points) > 1 else 0
        stats.append(
            GuessStats(
                average_distance=avg_dist,
                median_distance=statistics.median(distances),
                stddev_distance=stddev_dist,
                average_pts=avg_pts,
                median_pts=statistics.median(points),
                stddev_pts=stddev_pts,
                second_best_pts=second_best_pts,
                second_worst_pts=second_worst_pts,
                n_players=len(distances),
            )
        )

    return stats


GuessRanker = Callable[[Guess, GuessStats], float]


def absoulte_median_diff_points_ranker(guess: Guess, stats: GuessStats) -> float:
    return guess.score - stats.median_pts


def adjusted_median_points_ranker(guess: Guess, stats: GuessStats) -> float:
    return (guess.score - stats.median_pts) / 5000


def expected_distance_ranker(guess: Guess, stats: GuessStats) -> float:
    total_distance = stats.average_distance * stats.n_players
    pct_distance = guess.distance_km / total_distance
    return 1 - pct_distance


def expected_points_ranker(guess: Guess, stats: GuessStats) -> float:
    total_points = stats.average_pts * stats.n_players
    pct_points = guess.score / total_points
    return pct_points


def combined_ranker(guess: Guess, stats: GuessStats) -> float:
    return adjusted_median_points_ranker(guess, stats) + expected_distance_ranker(
        guess, stats
    )


def next_best_points_ranker(guess: Guess, stats: GuessStats) -> float:
    return guess.score - (stats.second_best_pts + stats.second_worst_pts) / 2


def get_ranked_guesses(
    round_result: ChallengeResult,
    guess_ranker: GuessRanker = next_best_points_ranker,
) -> list[RankedGuess]:
    """
    Rank all guesses in the round based on the provided guess_ranker function.
    Returns a list of RankedGuess objects sorted by adjusted score in descending order.
    """

    all_guess_stats = compute_stats(round_result)

    guess_data_with_adjusted_score = []

    for round_score in round_result.scores:
        for i, guess in enumerate(round_score.guesses):
            guess_stats = all_guess_stats[i]

            adjusted_score = guess_ranker(guess, guess_stats)
            guess_data_with_adjusted_score.append(
                RankedGuess(
                    player=round_score.player,
                    guess=guess,
                    guess_stats=guess_stats,
                    location_index=i + 1,
                    adjusted_score=adjusted_score,
                )
            )

    return sorted(
        guess_data_with_adjusted_score, key=lambda rg: rg.adjusted_score, reverse=True
    )
