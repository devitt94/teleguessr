from loguru import logger
import numpy as np
import polars as pl
import scipy.stats as stats
from scipy import optimize

from dataclasses import dataclass

M = 20015  # km

# --- Model ---


def neg_log_likelihood(params, data):
    mu, log_sigma = params
    sigma = np.exp(log_sigma)
    log_data = np.log(data)
    a = (np.log(M) - mu) / sigma
    ll = (
        -np.sum(log_data)
        - len(data) * np.log(sigma)
        - np.sum((log_data - mu) ** 2) / (2 * sigma**2)
        - len(data) * np.log(stats.norm.cdf(a))
    )
    return -ll


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
    player: str, distances: np.ndarray, min_rounds: int = 100
) -> FitResult | None:
    """Fit truncated lognormal for a single player. Returns None if insufficient data."""
    distances = distances[(distances > 0) & (distances < M)]

    if len(distances) < min_rounds:
        logger.info(
            f"Skipping {player} due to insufficient number of rounds ({len(distances)=} {min_rounds=})"
        )
        return None

    log_data = np.log(distances)
    mu0, sigma0 = log_data.mean(), log_data.std()

    result = optimize.minimize(
        neg_log_likelihood,
        x0=[mu0, np.log(max(sigma0, 1e-3))],
        args=(distances,),
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

    return FitResult(
        player=player,
        mu=mu_hat,
        sigma=sigma_hat,
        n_rounds=len(distances),
        converged=result.success,
        mean_km=mean_km,
        median_km=median_km,
    )


def fit_all_players(df: pl.DataFrame, min_rounds: int = 100) -> dict[str, FitResult]:
    results = {}

    for player, group in df.group_by("player"):
        distances = group["distance_km"].to_numpy()
        fit = fit_player(player[0], distances, min_rounds=min_rounds)
        if fit is not None:
            results[player[0]] = fit

    return results
