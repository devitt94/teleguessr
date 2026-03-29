import json
from pathlib import Path

from loguru import logger

from teleguessr.geoguessr_scraper import GeoguessrClient

import dotenv

import numpy as np
import polars as pl
from scipy import optimize, stats
from dataclasses import dataclass

from teleguessr.models import ChallengeResult
from teleguessr.settings import get_settings
from teleguessr.handicaps import get_latest_handicaps

_POLARS_AVAILABLE = False

try:
    import polars as pl

    _POLARS_AVAILABLE = True
except ImportError:
    logger.warning(
        "Polars is not installed. Install it with 'pip install polars' to enable handicap analysis."
    )


dotenv.load_dotenv()

LEGACY_CHALLENGE_URLS = {
    # Legacy challenge URLs from previous leagues before recording was automated
    "https://www.geoguessr.com/challenge/07YmhmGm8GGWkvqk",
    "https://www.geoguessr.com/challenge/0FbrbTeS2iebcJ5p",
    "https://www.geoguessr.com/challenge/0Op7RL0HQrBuuiEH",
    "https://www.geoguessr.com/challenge/1AXQo2ZhvZNKWf3m",
    "https://www.geoguessr.com/challenge/1BskAmL7qZPwHtc7",
    "https://www.geoguessr.com/challenge/3nwNDCuiIB2FcakK",
    "https://www.geoguessr.com/challenge/4psl92OpHr4PPbPd",
    "https://www.geoguessr.com/challenge/4rLqwPsFiGqdb0H0",
    "https://www.geoguessr.com/challenge/5WZvm8hdnzw97f5M",
    "https://www.geoguessr.com/challenge/6eNCF3REhfmW23YN",
    "https://www.geoguessr.com/challenge/6wPlUsUgjQHtAbYw",
    "https://www.geoguessr.com/challenge/7n9kRNbdXHHNmkJU",
    "https://www.geoguessr.com/challenge/8mlulFdDRIQ560n9",
    "https://www.geoguessr.com/challenge/AdXr1FPo7oukdSHh",
    "https://www.geoguessr.com/challenge/B2Fd2UeSvlCrj4x1",
    "https://www.geoguessr.com/challenge/CjeCMC1w8bhRPuUS",
    "https://www.geoguessr.com/challenge/F1a0CJ2zEzU7MFvX",
    "https://www.geoguessr.com/challenge/FDJefDJKQt3KEQ4m",
    "https://www.geoguessr.com/challenge/IkFE3xkmSEwuKN2p",
    "https://www.geoguessr.com/challenge/JS7SSlJOT7qhS2WZ",
    "https://www.geoguessr.com/challenge/KpCrkYYN5Ps9auH4",
    "https://www.geoguessr.com/challenge/MRD3Q3ZJv8CblhrJ",
    "https://www.geoguessr.com/challenge/NW5zhdlXHN4cGr2T",
    "https://www.geoguessr.com/challenge/Od9jempwRGjv85a0",
    "https://www.geoguessr.com/challenge/TPF2H2QoGahBwBbI",
    "https://www.geoguessr.com/challenge/UCDRId930Z9dBi40",
    "https://www.geoguessr.com/challenge/UWNm6R5AkoWMxsk4",
    "https://www.geoguessr.com/challenge/Us1oCYKKga5mjSHm",
    "https://www.geoguessr.com/challenge/ViWGMvi4AT68u3qa",
    "https://www.geoguessr.com/challenge/WdCalSH2HvpSz8yQ",
    "https://www.geoguessr.com/challenge/WvbdX0rQal3n3tCR",
    "https://www.geoguessr.com/challenge/ZR5KuMYAbptcUXJY",
    "https://www.geoguessr.com/challenge/ZeM71qobK673WG5U",
    "https://www.geoguessr.com/challenge/dxNQNpm2Kq3FY40M",
    "https://www.geoguessr.com/challenge/e6o4lPRb8pplt4WN",
    "https://www.geoguessr.com/challenge/eghmKGH0l3kxmw8x",
    "https://www.geoguessr.com/challenge/fVZyhw9DACjglhRt",
    "https://www.geoguessr.com/challenge/hgXMTze1n5YQMm2n",
    "https://www.geoguessr.com/challenge/jYq1U9Tz1iCg2QOx",
    "https://www.geoguessr.com/challenge/kMM7KPqv8NRLyHAI",
    "https://www.geoguessr.com/challenge/ltvNfFHZ9WxktRYb",
    "https://www.geoguessr.com/challenge/mimM6MJFIi0rmfGz",
    "https://www.geoguessr.com/challenge/rHFDspYYFQtHwRQO",
    "https://www.geoguessr.com/challenge/sljCBcLoBY0VsBMX",
    "https://www.geoguessr.com/challenge/vdDpVWYbrsmVnfkq",
    "https://www.geoguessr.com/challenge/xUMqtBmmA0CgDF2z",
    "https://www.geoguessr.com/challenge/xa6eMHpfS6jI5fSx",
    "https://www.geoguessr.com/challenge/zqNphEoeQLOuaPnu",
}

FINISHED_LEAGUES_DIR = Path("data/leagues/finished/")
MAX_DISTANCE_KM = 20015  # Max possible distance on Earth, used for lognormal truncation

NAME_CHANGES = {
    "Boothd": "Boothlandia",
    "Danminican Republic": "Danquador Junta State",
}


def get_challenge_results_from_finished_leagues() -> list[ChallengeResult]:
    results = []
    for league_file in FINISHED_LEAGUES_DIR.glob("league_*.json"):
        with open(league_file, "r") as f:
            league_data = json.load(f)
        for round_info in league_data["results"]:
            results.append(ChallengeResult(**round_info))

    return results


async def get_legacy_challenge_results(
    geoguessr_client: GeoguessrClient,
) -> list[ChallengeResult]:
    results = []
    for challenge_url in LEGACY_CHALLENGE_URLS:
        result = await geoguessr_client.get_challenge_scores(challenge_url, {}, 0.0)
        results.append(result)

    return results


async def get_all_challenge_results(
    include_legacy_rounds: bool = False,
) -> list[ChallengeResult]:
    results = get_challenge_results_from_finished_leagues()
    if include_legacy_rounds:
        logger.info("Including legacy rounds in analysis...")
        settings = get_settings()
        client = GeoguessrClient(
            ncfa_cookie=settings.geoguessr_ncfa_cookie
        )  # Add valid cookie if needed
        legacy_results = await get_legacy_challenge_results(client)
        results.extend(legacy_results)

    return results


async def get_score_data(
    include_legacy_rounds: bool = False,
) -> pl.DataFrame:
    results = await get_all_challenge_results(include_legacy_rounds)

    data = []
    for round_result in results:
        if len(round_result.scores) < 3:
            logger.info(
                f"Skipping challenge {round_result.challenge_url} due to insufficient players ({len(round_result.scores)})"
            )
            continue

        for player_score in round_result.scores:
            player_name = NAME_CHANGES.get(
                player_score.player.name, player_score.player.name
            )
            for i, guess in enumerate(player_score.guesses):
                data.append(
                    {
                        "player": player_name,
                        "score": guess.score,
                        "distance_km": guess.distance_km,
                        "challenge_id": round_result.challenge_url.split("/")[-1],
                        "round_index": i + 1,
                    }
                )

    df = pl.DataFrame(data)
    return df


async def average_scores(include_legacy_rounds: bool = False) -> pl.DataFrame:
    df = await get_score_data(include_legacy_rounds)
    average_scores = df.group_by("player").agg(
        pl.col("score").mean().alias("average_score"),
        pl.col("score").std().alias("std_dev_score"),
        pl.col("distance_km").mean().alias("average_distance_km"),
        pl.col("distance_km").std().alias("std_dev_distance_km"),
        pl.count("score").alias("num_guesses"),
    )
    average_scores = average_scores.sort("average_score", descending=True)
    logger.info(f"Average Gross Scores:\n\n{average_scores}\n")
    return average_scores


async def round_analysis(
    include_legacy_rounds: bool = False,
):
    data = []

    for result in await get_all_challenge_results(include_legacy_rounds):
        url = result.challenge_url
        for player_score in result.scores:
            data.append(
                {
                    "player": NAME_CHANGES.get(
                        player_score.player.name, player_score.player.name
                    ),
                    "round_id": url.split("/")[-1],
                    "gross_score": player_score.gross_score,
                }
            )

    logger.info("Top 5 Gross Scores:")
    sorted_by_gross = sorted(data, key=lambda x: x["gross_score"], reverse=True)
    for entry in sorted_by_gross[:5]:
        logger.info(
            f"\t{entry['player']} - Round {entry['round_id']}: Gross Score = {entry['gross_score']}"
        )

    logger.info("Bottom 5 Gross Scores:")
    for entry in sorted_by_gross[-5::-1]:
        logger.info(
            f"\t{entry['player']} - Round {entry['round_id']}: Gross Score = {entry['gross_score']}"
        )


async def handicap_analysis(
    include_legacy_rounds: bool = False,
):
    data = []

    if not _POLARS_AVAILABLE:
        logger.error(
            "Polars is required for handicap analysis. Please install it with 'pip install polars'."
        )
        return

    current_handicaps = get_latest_handicaps()

    for result in await get_all_challenge_results(include_legacy_rounds):
        url = result.challenge_url
        for player_score in result.scores:
            for i, guess in enumerate(player_score.guesses):
                data.append(
                    {
                        "player": NAME_CHANGES.get(
                            player_score.player.name, player_score.player.name
                        ),
                        "round_id": url.split("/")[-1],
                        "guess_index": i + 1,
                        "guess_score": guess.score,
                    }
                )
    df = pl.DataFrame(data)

    if df.is_empty():
        logger.warning("No guess data available for handicap analysis.")
        return

    average_scores = df.group_by("player").agg(
        pl.col("guess_score").mean().alias("average_guess")
    )
    average_scores = average_scores.sort("average_guess", descending=True)

    max_average_guess = average_scores["average_guess"].max()
    average_scores = average_scores.with_columns(
        pl.Series(
            "fair_handicap_pct",
            [
                100 * (max_average_guess - avg) / (5000 - avg)
                for avg in average_scores["average_guess"]
            ],
        )
    )
    average_scores = average_scores.with_columns(
        pl.Series(
            "current_handicap_pct",
            [
                current_handicaps.get(player, 0) * 100
                for player in average_scores["player"]
            ],
        )
    )
    average_scores = average_scores.with_columns(
        pl.Series(
            "diff",
            average_scores["fair_handicap_pct"]
            - average_scores["current_handicap_pct"],
        )
    ).sort("fair_handicap_pct")

    logger.info(f"Fair Handicap Analysis:\n\n{average_scores}\n")


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
