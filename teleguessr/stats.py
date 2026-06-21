from datetime import timedelta

from loguru import logger
import numpy as np
import polars as pl
import scipy.stats as stats
from scipy import optimize

from dataclasses import dataclass

M = 20015  # km

# --- Model ---


def neg_log_likelihood(
    params: np.ndarray,
    distances: np.ndarray,
    weights: np.ndarray,
) -> float:
    mu, log_sigma = params
    sigma = np.exp(log_sigma)

    a = (np.log(M) - mu) / sigma
    log_norm_const = np.log(stats.norm.cdf(a))

    log_pdf = stats.lognorm.logpdf(distances, s=sigma, scale=np.exp(mu))
    weighted_nll = -np.sum(weights * (log_pdf - log_norm_const))
    return weighted_nll


@dataclass
class FitResult:
    player: str
    mu: float
    sigma: float
    n_rounds: int
    converged: bool
    mean_km: float  # implied mean distance
    median_km: float  # implied median distance

    def simulate_guess(self) -> float:
        """Simulate a guess distance in km based on the fitted distribution."""
        a = (np.log(M) - self.mu) / self.sigma
        simulated_log_distance = self.mu + self.sigma * stats.norm.ppf(
            np.random.uniform(0, stats.norm.cdf(a))
        )
        return np.exp(simulated_log_distance)


def fit_player(
    player: str,
    distances: np.ndarray,
    weights: np.ndarray,
    min_rounds: int = 100,
    adjustment: float = 0.0,
) -> FitResult | None:
    """Fit truncated lognormal for a single player. Returns None if insufficient data."""
    distances = distances[(distances > 0) & (distances < M)]

    if adjustment != 0.0:
        logger.info(f"Applying adjustment of {adjustment} to player {player}")
        distances = distances * (1 + adjustment)  # Apply any player-specific adjustment

    if len(distances) < min_rounds:
        logger.info(
            f"Skipping {player} due to insufficient number of rounds ({len(distances)=} {min_rounds=})"
        )
        return None

    if player == "Horanje":
        logger.info(f"Skipping {player} due to known data issues")
        return None

    log_data = np.log(distances)
    mu0, sigma0 = log_data.mean(), log_data.std()

    result = optimize.minimize(
        neg_log_likelihood,
        x0=[mu0, np.log(max(sigma0, 1e-3))],
        args=(distances, weights),
        method="L-BFGS-B",
    )

    mu_hat = result.x[0]
    sigma_hat = np.exp(result.x[1])

    # Implied distribution moments
    a = (np.log(M) - mu_hat) / sigma_hat
    mean_km = (
        np.exp(mu_hat + sigma_hat**2 / 2)
        * stats.norm.cdf(a - sigma_hat)
        / stats.norm.cdf(a)
    )
    median_km = np.exp(
        mu_hat
    )  # median of lognormal is just exp(mu), truncation barely affects it

    res = FitResult(
        player=player,
        mu=mu_hat,
        sigma=sigma_hat,
        n_rounds=len(distances),
        converged=result.success,
        mean_km=mean_km,
        median_km=median_km,
    )
    print(
        f"Fitted {player}: mu={mu_hat:.4f}, sigma={sigma_hat:.4f}, mean_km={mean_km:.2f}, median_km={median_km:.2f}"
    )
    return res


def fit_all_players(
    df: pl.DataFrame, adjustments: dict[str, float] = None, min_rounds: int = 100
) -> dict[str, FitResult]:
    results = {}

    default_challenge_date = df["challenge_date"].min() - timedelta(days=7)
    current_date = df["challenge_date"].max()
    # Fill null challenge dates with the minimum date to avoid issues in grouping
    df = df.with_columns(pl.col("challenge_date").fill_null(default_challenge_date))

    df = df.with_columns(
        ((current_date - pl.col("challenge_date")).dt.total_days() / 7).alias(
            "weeks_ago"
        )
    )

    df = df.with_columns(
        pl.col("weeks_ago")
        .map_elements(lambda x: 0.5 ** (x / 8))
        .alias("decay_weight")  # half-life of 6 weeks
    )

    for player, group in df.group_by("player"):
        distances = group["distance_km"].to_numpy()
        weights = group["decay_weight"].to_numpy()
        player_adjustment = adjustments.get(player[0], 0.0)
        fit = fit_player(
            player[0],
            distances,
            weights,
            min_rounds=min_rounds,
            adjustment=player_adjustment,
        )
        if fit is not None:
            results[player[0]] = fit

    results["Commissioner Perez"] = FitResult(
        player="Commissioner Perez",
        mu=7.35,
        sigma=2.2,
        n_rounds=100,
        converged=True,
        mean_km=3250.0,
        median_km=2250.0,
    )

    return results
