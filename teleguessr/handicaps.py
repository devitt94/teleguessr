from datetime import date, timedelta
import json

from loguru import logger

from teleguessr.settings import LeagueSettings


def get_latest_handicaps(league_settings: LeagueSettings) -> dict[str, float]:
    handicap_files = sorted(league_settings.handicaps_dir.glob("*.json"), reverse=True)

    if not handicap_files:
        raise FileNotFoundError("No handicap files found in data/handicaps/")

    latest_file = handicap_files[0]

    logger.info(f"Loading player handicaps from {latest_file}")
    with latest_file.open("r") as f:
        handicaps = json.load(f)

    return handicaps


def get_adjustments(num_players: int) -> list[float]:
    """Generate handicap adjustments based on player rankings."""

    if num_players == 0:
        return []
    elif num_players == 1:
        return [0.0]

    max_adjustment = 0.01 * (num_players // 2)
    return [
        round(
            (i - (num_players - 1) / 2) * (max_adjustment / ((num_players - 1) / 2)), 2
        )
        for i in range(num_players)
    ]


def calculate_new_handicaps(
    player_ranks: dict[str, int], league_settings: LeagueSettings
) -> dict[str, float]:
    """Calculate new handicaps based on recent league results."""
    current_handicaps = get_latest_handicaps(league_settings)

    adjustments = get_adjustments(len(player_ranks))
    new_handicaps: dict[str, float] = {}

    for player, rank in player_ranks.items():
        adjustment = adjustments[rank - 1]
        current_handicap = current_handicaps.get(
            player, league_settings.default_handicap_multiplier
        )

        new_handicap = current_handicap + adjustment
        logger.info(
            f"Player: {player}, Rank: {rank}, Current Handicap: {current_handicap}, Adjustment: {adjustment}, New Handicap: {new_handicap}"
        )
        new_handicaps[player] = round(new_handicap, 2)

    # Find the minimum among players who participated
    if new_handicaps:
        min_new_handicap = min(new_handicaps.values())
    else:
        min_new_handicap = 0.0

    # Add unchanged handicaps for players not in the recent league BEFORE normalization
    # to find the global minimum
    for player, handicap in current_handicaps.items():
        if player not in new_handicaps:
            new_handicaps[player] = handicap
            min_new_handicap = min(min_new_handicap, handicap)

    normalization_adjustment = min_new_handicap * -1

    # Only normalize players who participated in the league
    for player in player_ranks.keys():
        logger.info(
            f"Normalizing Player: {player}, Pre-Normalization Handicap: {new_handicaps[player]}, Adjustment: {normalization_adjustment}"
        )
        new_handicaps[player] = round(
            new_handicaps[player] + normalization_adjustment, 2
        )
        if new_handicaps[player] > league_settings.max_handicap_multiplier:
            logger.info(
                f"Capping Player: {player}, Handicap before cap: {new_handicaps[player]}"
            )
            new_handicaps[player] = league_settings.max_handicap_multiplier

    return new_handicaps


def update_handicaps(
    new_handicaps: dict[str, float], league_date: date, league_settings: LeagueSettings
) -> None:
    league_settings.handicaps_dir.mkdir(parents=True, exist_ok=True)
    next_league_start_date = league_date + timedelta(days=7)
    latest_file = (
        league_settings.handicaps_dir
        / f"handicaps_league_{next_league_start_date.strftime('%Y%m%d')}.json"
    )

    with latest_file.open("w") as f:
        json.dump(new_handicaps, f, indent=4)

    logger.info(f"Updated player handicaps saved to {latest_file}")
