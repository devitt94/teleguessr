from copy import deepcopy
import json
from pathlib import Path
import random
import multiprocessing
import numpy as np
from functools import partial
from loguru import logger

from teleguessr.stats import FitResult, fit_all_players
from teleguessr.odds import (
    probs_to_odds,
)
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
    lognormal_fits: dict[str, FitResult],
    league_state: LeagueState,
    challenge_settings_generator: ChallengeSettingsGenerator,
    n_rounds: int,
    hcaps: dict[str, float],
) -> LeagueState:
    while not league_state.is_finished:
        challenge_settings = challenge_settings_generator(
            league_state.current_round_num
        )

        streamer = None
        if league_state.current_round_num == n_rounds - 1:
            mu_adjustment = 0.25
            streamer = random.choice(league_state.current_leaders)
            lognormal_fits[streamer].mu += mu_adjustment

        round_result = _simulate_round(lognormal_fits, hcaps, challenge_settings)
        ranked_guesses = get_ranked_guesses(round_result)
        league_state.add_round_result(round_result)
        league_state.add_awards(ranked_guesses[0], ranked_guesses[-1])

        if streamer is not None:
            lognormal_fits[streamer].mu -= mu_adjustment
            streamer = None

    return league_state


def simulate_n_leagues(
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
        if i % 100 == 0:
            logger.info(f"Simulating league {i}/{n_sims}")

        sim_init_state: LeagueState = deepcopy(league_state)

        final_state: LeagueState = _simulate_league(
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


def simulate_n_leagues_parallel(
    lognormal_fits: dict[str, FitResult],
    n_sims: int,
    league_settings: LeagueSettings,
    hcaps: dict[str, float],
    league_state_file: Path | None = None,
) -> pl.DataFrame:
    n_workers = multiprocessing.cpu_count()
    sims_per_worker = n_sims // n_workers
    logger.info(
        f"Running {n_sims} simulations across {n_workers} workers ({sims_per_worker} sims/worker)"
    )

    simulate = partial(
        simulate_n_leagues,
        lognormal_fits,
        league_settings=league_settings,
        hcaps=hcaps,
        league_state_file=league_state_file,
    )

    # Split total sims evenly across workers
    sims_per_worker = n_sims // n_workers
    sim_counts = [sims_per_worker] * n_workers
    sim_counts[-1] += n_sims - sum(sim_counts)  # remainder to last worker

    with multiprocessing.Pool(processes=n_workers) as pool:
        results = pool.map(simulate, sim_counts)

    combined_df = pl.concat(results, how="vertical")
    return combined_df


def outright_win_probabilities(sim_df: pl.DataFrame) -> pl.DataFrame:
    """
    Input dataframe contains a column for each player, and row i represents the player scores for simulation i.

    Based on this, compute the probabilities of each player coming first.
    """

    player_cols = sim_df.columns

    sim_df = sim_df.with_columns(
        pl.Series(
            [
                player_cols[max(range(len(player_cols)), key=lambda i: row[i])]
                for row in sim_df.select(player_cols).iter_rows()
            ]
        ).alias("winner"),
        pl.Series(
            [
                player_cols[min(range(len(player_cols)), key=lambda i: row[i])]
                for row in sim_df.select(player_cols).iter_rows()
            ]
        ).alias("loser"),
    )

    win_probs = sim_df.group_by("winner").agg(
        (pl.len() / sim_df.height).alias("win_probability")
    )

    wooden_spoon_probs = sim_df.group_by("loser").agg(
        (pl.len() / sim_df.height).alias("wooden_spoon_probability")
    )

    return (
        win_probs.join(
            wooden_spoon_probs,
            left_on="winner",
            right_on="loser",
            how="full",
            coalesce=True,
        )
        .select(
            pl.col("winner").alias("player"),
            pl.col("win_probability"),
            pl.col("wooden_spoon_probability"),
        )
        .sort("win_probability", descending=True)
        .fill_null(0.0)
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


def fractional_odds_to_decimal(odds: str) -> float:
    try:
        numerator, denominator = map(float, odds.split("/"))
    except Exception:
        return float("nan")
    return numerator / denominator + 1


async def generate_outright_odds_predictions(
    n_sims: int,
    include_legacy_rounds: bool = False,
) -> pl.DataFrame:
    score_data: pl.DataFrame = await get_score_data(
        include_legacy_rounds=include_legacy_rounds
    )
    settings = get_settings()
    league_settings = settings.league
    active_dir = settings.data_dir / "leagues" / "active"
    try:
        latest_active_league_file = sorted(active_dir.glob("*.json"), reverse=True)[0]
    except IndexError:
        logger.warning("No active league found.")
        latest_active_league_file = None

    hcaps = get_latest_handicaps(league_settings)

    adjustments_file = settings.data_dir / "adjustments" / "adjustments.json"
    if adjustments_file.exists():
        with open(adjustments_file, "r") as f:
            adjustments = json.load(f)
    else:
        adjustments = {}

    logger.info(f"Using adjustments: {adjustments}")
    lognormal_fits = fit_all_players(score_data, adjustments=adjustments)

    sim_results = simulate_n_leagues_parallel(
        lognormal_fits,
        n_sims=n_sims,
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

    all_df = all_df.sort("win_probability", descending=True)

    win_odds = probs_to_odds(
        all_df["win_probability"].to_list(),
    )

    ws_odds = probs_to_odds(
        all_df["wooden_spoon_probability"].to_list(),
    )

    all_df = all_df.with_columns(
        [
            pl.Series(
                "back_win_odds",
                [f.formatted if f is not None else None for f in win_odds],
            ),
            pl.Series(
                "back_win_implied_prob",
                [f.implied_probability if f is not None else None for f in win_odds],
            ),
            pl.Series(
                "back_ws_odds",
                [f.formatted if f is not None else None for f in ws_odds],
            ),
            pl.Series(
                "back_ws_implied_prob",
                [f.implied_probability if f is not None else None for f in ws_odds],
            ),
        ]
    )

    all_df = all_df.with_columns(
        (pl.col("handicap_multiplier") * 100)
        .round(0)
        .cast(pl.String)
        .alias("handicap_pct"),
        (pl.col("win_probability") * 100).round(2).cast(pl.String).alias("win_pct"),
        (pl.col("wooden_spoon_probability") * 100)
        .round(2)
        .cast(pl.String)
        .alias("wooden_spoon_pct"),
        pl.col("mean_guess_distance_km").round(2).alias("mean_guess_distance_km"),
        pl.col("median_guess_distance_km").round(2).alias("median_guess_distance_km"),
    ).select(
        "player",
        "win_pct",
        "wooden_spoon_pct",
        "back_win_odds",
        "back_win_implied_prob",
        "back_ws_odds",
        "back_ws_implied_prob",
    )

    return all_df
