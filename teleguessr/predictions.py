import asyncio
from copy import deepcopy
from pathlib import Path

import numpy as np
from loguru import logger

from teleguessr.stats import FitResult, fit_all_players
from teleguessr.analysis import get_score_data
from teleguessr.awards import get_ranked_guesses
from teleguessr.handicaps import get_latest_handicaps
from teleguessr.league import LeagueState

import polars as pl

from teleguessr.models import (
    ChallengeResult,
    ChallengeScore,
    ChallengeSettings,
    Guess,
    Player,
)
from teleguessr.settings import LeagueSettings, get_settings
from teleguessr.challenge_settings_generators import (
    CHALLENGE_SETTINGS,
    ChallengeSettingsGenerator,
)


def _simulate_round(
    lognormal_fits: dict[str, FitResult],
    hcaps: dict[str, float],
    challenge_settings: ChallengeSettings,
) -> ChallengeResult:
    scores: list[ChallengeScore] = []
    for player, fit in lognormal_fits.items():
        handicap_multiplier = hcaps.get(player, 0.0)

        player_guesses: list[Guess] = []
        for i in range(challenge_settings.number_of_locations):
            simulated_guess_distance = fit.simulate_guess()
            simulated_guess_score = compute_geoguessr_score(simulated_guess_distance)
            player_guesses.append(
                Guess(score=simulated_guess_score, distance_km=simulated_guess_distance)
            )

        scores.append(
            ChallengeScore(
                player=Player(name=player, hcap_multiplier=handicap_multiplier),
                guesses=player_guesses,
            )
        )

    return ChallengeResult(
        challenge_url="simulated", scores=scores, challenge_settings=challenge_settings
    )


def _simulate_league(
    i: int,
    lognormal_fits: dict[str, FitResult],
    league_state: LeagueState,
    challenge_settings_generator: ChallengeSettingsGenerator,
    n_rounds: int,
    hcaps: dict[str, float],
) -> LeagueState:
    while not league_state.is_finished:
        challenge_settings = challenge_settings_generator(i)
        round_result = _simulate_round(lognormal_fits, hcaps, challenge_settings)
        ranked_guesses = get_ranked_guesses(round_result)
        league_state.add_round_result(round_result)
        league_state.add_awards(ranked_guesses[0], ranked_guesses[-1])
    return league_state


def simulate_league(
    lognormal_fits: dict[str, FitResult],
    n_sims: int,
    league_settings: LeagueSettings,
    hcaps: dict[str, float],
    league_state_file: Path | None = None,
) -> pl.DataFrame:
    league_final_leaderboards = []

    logger.info(f"Running {n_sims} simulations")
    challenge_settings_generator = CHALLENGE_SETTINGS[
        league_settings.challenge_settings_name
    ]

    if league_state_file is None:
        logger.info("No active league state found, simulating from scratch")
        league_state = LeagueState(
            filepath="/tmp/simulated_league.json",
            num_rounds=league_settings.number_of_rounds,
        )
    else:
        logger.info(f"Loading active league state from {league_state_file}")
        league_state = LeagueState(
            filepath=league_state_file, num_rounds=league_settings.number_of_rounds
        )
        league_state.load_from_file()
        current_round = league_state.current_round_num
        scores = league_state.get_leaderboard_data()["scores"]
        logger.info(f"Simulating from state {current_round=} with {scores=}")

    for i in range(n_sims):
        sim_init_state: LeagueState = deepcopy(league_state)
        if i % 1000 == 0:
            logger.info(f"Simulated league {i}/{n_sims}")

        final_state: LeagueState = _simulate_league(
            i,
            lognormal_fits,
            sim_init_state,
            challenge_settings_generator,
            league_settings.number_of_rounds,
            hcaps,
        )
        final_leaderboard = final_state.get_leaderboard_data()
        player_scores = final_leaderboard["scores"]
        league_final_leaderboards.append(player_scores)

    df = pl.DataFrame(league_final_leaderboards)

    return df


def percentage_to_fractional_odds(
    percentage: float,
    bounds_direction: int = 0,
) -> str:
    """
    Convert a probability percentage to the nearest commonly used fractional betting odds.

    Args:
        percentage: A probability value between 0 and 100 (exclusive).
        bounds_direction: If value is 1, round up instead of to nearest, to ensure
            odds are at least as long as implied by percentage. If -1, round down.

    Returns:
        A string representing the fractional odds (e.g. "5/2").

    Raises:
        ValueError: If percentage is not in the valid range (0, 100).
    """
    if not (0 < percentage < 100):
        return "-"

    # All standard fractional odds from the AceOdds conversion table,
    # stored as (numerator, denominator) tuples, ordered from shortest to longest odds.
    COMMON_FRACTIONS = [
        (1, 100),
        (1, 5),
        (2, 9),
        (1, 4),
        (2, 7),
        (3, 10),
        (1, 3),
        (4, 11),
        (2, 5),
        (4, 9),
        (1, 2),
        (8, 15),
        (4, 7),
        (8, 13),
        (4, 6),
        (8, 11),
        (4, 5),
        (5, 6),
        (10, 11),
        (1, 1),
        (21, 20),
        (11, 10),
        (23, 20),
        (6, 5),
        (5, 4),
        (11, 8),
        (7, 5),
        (6, 4),
        (8, 5),
        (13, 8),
        (7, 4),
        (9, 5),
        (15, 8),
        (2, 1),
        (11, 5),
        (9, 4),
        (12, 5),
        (5, 2),
        (13, 5),
        (11, 4),
        (3, 1),
        (16, 5),
        (10, 3),
        (7, 2),
        (4, 1),
        (9, 2),
        (5, 1),
        (11, 2),
        (6, 1),
        (13, 2),
        (7, 1),
        (15, 2),
        (8, 1),
        (9, 1),
        (10, 1),
        (11, 1),
        (12, 1),
        (13, 1),
        (14, 1),
        (15, 1),
        (16, 1),
        (18, 1),
        (20, 1),
        (25, 1),
        (33, 1),
        (50, 1),
        (66, 1),
        (100, 1),
        (1000, 1),
    ]

    # Convert percentage to an implied probability (0–1)
    prob = percentage / 100.0

    # Find the fraction whose implied probability is closest to the input.
    # Implied probability of fractional odds n/d = d / (n + d)
    def implied_prob(n, d):
        return d / (n + d)

    if bounds_direction == 1:
        # Filter to fractions that are at least as long as implied by percentage
        COMMON_FRACTIONS = [
            (n, d) for n, d in COMMON_FRACTIONS if implied_prob(n, d) <= prob
        ]
    elif bounds_direction == -1:
        # Filter to fractions that are at most as long as implied by percentage
        COMMON_FRACTIONS = [
            (n, d) for n, d in COMMON_FRACTIONS if implied_prob(n, d) >= prob
        ]
    else:
        best = min(COMMON_FRACTIONS, key=lambda nd: abs(implied_prob(*nd) - prob))
    return f"{best[0]}/{best[1]}"


def outright_win_probabilities(sim_df: pl.DataFrame):
    """
    Input dataframe contains a column for each player, and row i represents the player scores for simulation i.

    Based on this, compute the probabilities of each player coming first.
    """

    player_cols = sim_df.columns

    return (
        sim_df.with_columns(
            pl.Series(
                [
                    player_cols[max(range(len(player_cols)), key=lambda i: row[i])]
                    for row in sim_df.select(player_cols).iter_rows()
                ]
            ).alias("player")
        )
        .group_by("player")
        .agg((pl.len() / sim_df.height).alias("win_probability"))
        .sort("win_probability", descending=True)
    )


def compute_geoguessr_score(distance_km: float) -> int:
    k = 0.000539
    return int(5000 * np.exp(-k * distance_km))


def compute_h2h(
    sim_df: pl.DataFrame, player_a: str, player_b: str
) -> tuple[float, float, float]:
    """Compute the win/draw/loss probabilities of player A vs player B based on the simulation results"""
    if not (player_a in sim_df.columns and player_b in sim_df.columns):
        raise ValueError(f"Player missing {player_a=} {player_b=} {sim_df.columns=}")

    result = sim_df.select(
        [
            (pl.col(player_a) > pl.col(player_b)).mean().alias(f"{player_a}_W"),
            (pl.col(player_a) == pl.col(player_b)).mean().alias("draws"),
            (pl.col(player_a) < pl.col(player_b)).mean().alias(f"{player_b}_wins"),
        ]
    )
    return result.row(0)


if __name__ == "__main__":
    N_SIMS = 40_000
    OVERROUND = 0.25
    score_data: pl.DataFrame = asyncio.run(get_score_data(include_legacy_rounds=False))
    settings = get_settings()
    league_settings = settings.league
    active_dir = settings.data_dir / "leagues" / "active"
    try:
        latest_active_league_file = sorted(active_dir.glob("*.json"), reverse=True)[0]
    except IndexError:
        logger.warning("No active league found.")
        latest_active_league_file = None

    hcaps = get_latest_handicaps(league_settings)

    lognormal_fits = fit_all_players(score_data)

    sim_results = simulate_league(
        lognormal_fits,
        n_sims=N_SIMS,
        league_settings=league_settings,
        hcaps=hcaps,
        league_state_file=latest_active_league_file,
    )
    outright_preds = outright_win_probabilities(sim_results)

    # Join handicap and model fit data to preds table
    all_df = outright_preds.with_columns(
        pl.Series(
            "handicap_multiplier",
            [hcaps.get(player, 0.0) for player in outright_preds["player"]],
        ),
        pl.Series(
            "mean_guess_distance_km",
            [lognormal_fits[player].mean_km for player in outright_preds["player"]],
        ),
        pl.Series(
            "median_guess_distance_km",
            [lognormal_fits[player].median_km for player in outright_preds["player"]],
        ),
        pl.Series(
            "num_guesses",
            [lognormal_fits[player].n_rounds for player in outright_preds["player"]],
        ),
        pl.Series(
            "fit_mu", [lognormal_fits[player].mu for player in outright_preds["player"]]
        ),
        pl.Series(
            "fit_sigma",
            [lognormal_fits[player].sigma for player in outright_preds["player"]],
        ),
    )

    additive_overround_per_runner = OVERROUND / all_df.height

    all_df = all_df.with_columns(
        (pl.col("win_probability") * (1 + OVERROUND)).alias(
            "adjusted_win_probability_multiplicative"
        ),
        (pl.col("win_probability") + additive_overround_per_runner).alias(
            "adjusted_win_probability_additive"
        ),
    )

    all_df = all_df.with_columns(
        (
            (
                pl.col("adjusted_win_probability_multiplicative")
                + pl.col("adjusted_win_probability_additive")
            )
            / 2
        ).alias("back_win_probability"),
    )

    all_df = all_df.with_columns(
        (pl.col("handicap_multiplier") * 100)
        .round(0)
        .cast(pl.String)
        .alias("handicap_pct"),
        (pl.col("win_probability") * 100).round(2).cast(pl.String).alias("win_pct"),
        pl.col("mean_guess_distance_km").round(2).alias("mean_guess_distance_km"),
        pl.col("median_guess_distance_km").round(2).alias("median_guess_distance_km"),
        (pl.col("back_win_probability") * 100)
        .round(2)
        .cast(pl.String)
        .alias("back_win_pct"),
        (pl.col("back_win_probability") * 100)
        .map_elements(percentage_to_fractional_odds)
        .alias("back_win_odds"),
    ).select(
        "player",
        "back_win_odds",
        "win_pct",
        "back_win_pct",
        "adjusted_win_probability_multiplicative",
        "adjusted_win_probability_additive",
    )

    # Print the player and adjusted_win_odds columns only
    print(all_df)

    # for p1, p2 in itertools.permutations(sim_results.columns, 2):
    #     win, draw, loss = compute_h2h(sim_results, p1, p2)
    #     print(f"{p1} vs {p2}: W={win}, D={draw}, L={loss}")
