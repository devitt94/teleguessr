import statistics
from models import Award, Awards, Guess, ChallengeResult, GuessStats, RankedGuess


def compute_stats(round_result: ChallengeResult) -> list[GuessStats]:
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
                median_distance=statistics.median(distances),
                stddev_distance=stddev_dist,
                average_pts=avg_pts,
                median_pts=statistics.median(points),
                stddev_pts=stddev_pts,
            )
        )

    return stats

def get_rayleigh_scores(round_result: ChallengeResult) -> dict[tuple[str, int], float]:
    """
    Compute Rayleigh scores for each player's guesses in the round.
    Returns a dictionary mapping (player_name, location_index) to Rayleigh score.
    """
    scores = {}
    def rayleigh_sigma_hat(distances: list[float]) -> float:
        # distances: list of numbers (km)
        n = len(distances)
        sum_sq = sum(r*r for r in distances)
        sigma_hat = (sum_sq / (2*n)) ** 0.5
        return sigma_hat
    
    def rayleigh_percentile(distance: float, sigma_hat: float) -> float:
        from math import exp
        percentile = 1 - exp(-(distance ** 2) / (2 * sigma_hat ** 2))
        return percentile
    
    for i in range(5):  # assuming 5 locations
        guesses = round_result.get_round_guesses(i)
        distances = {player: guess.distance_km for player, guess in guesses.items()}
        for player, distance in distances.items():
            other_distances = [distances[p] for p in distances if p != player]
            sigma_hat = rayleigh_sigma_hat(other_distances)
            percentile = rayleigh_percentile(distance, sigma_hat)
            scores[(player, i+1)] = percentile * 100  # convert to percentage
        
    return scores


def get_ranked_guesses(
    round_result: ChallengeResult
) -> list[RankedGuess]:
    """
    Identify the best and worst guesses in a round based on z-scores.
    Returns an Awards object containing the best and worst guesses.
    """

    rayleigh_scores = get_rayleigh_scores(round_result)

    all_guess_stats = compute_stats(round_result)

    guess_data_with_rayleigh = []

    for round_score in round_result.scores:
        for i, guess in enumerate(round_score.guesses):
            guess_stats = all_guess_stats[i]
            guess_rayleigh_score = rayleigh_scores[(round_score.player.name, i + 1)]
            guess_data_with_rayleigh.append(
                RankedGuess(
                    player=round_score.player,
                    guess=guess,
                    guess_stats=guess_stats,
                    location_index=i + 1,
                    rayleigh_score=guess_rayleigh_score
                )
            )
    
    sorted_by_rayleigh = sorted(
        guess_data_with_rayleigh,
        key=lambda rg: rg.rayleigh_score,
    )

    return sorted_by_rayleigh

