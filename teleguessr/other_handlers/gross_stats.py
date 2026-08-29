"""All-time gross (handicap-free) statistics computed from finished league files.

Everything the rest of the bot reports is net of handicaps. This module ignores
handicaps entirely and re-ranks every round on raw Geoguessr points, so the
numbers answer "who is actually the best player" rather than "who won".

Self-contained on purpose: nothing else in the codebase imports from here.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from enum import StrEnum
import json
from pathlib import Path

from pydantic import BaseModel

from teleguessr.models import ChallengeResult, ChallengeScore
from teleguessr.ranks import get_ranks_from_scores


# Mirrors teleguessr.analysis.NAME_CHANGES. Duplicated rather than imported so
# this module stays free of the analysis extras (polars, dotenv, the scraper).
NAME_CHANGES = {
    "Boothd": "Boothlandia",
    "Danminican Republic": "Danquador Junta State",
    "Commissioner Perez": "Ashghanistani Dem Rep Mikistan",
}

# Rounds with fewer finishers than this are ignored: positions in a two-horse
# race say nothing useful about anyone's ability.
MIN_FINISHERS_PER_ROUND = 3


class SortKey(StrEnum):
    """How to order the players in the table."""

    POINTS_PER_LOCATION = "avg"
    AVERAGE_POSITION = "pos"
    TOTAL_POINTS = "total"
    ROUND_WINS = "wins"

    @classmethod
    def parse(cls, value: str | None) -> "SortKey":
        if not value:
            return cls.POINTS_PER_LOCATION
        try:
            return cls(value.strip().lower())
        except ValueError:
            return cls.POINTS_PER_LOCATION


class PlayerGrossStats(BaseModel):
    """Aggregated handicap-free statistics for a single player."""

    player: str
    rounds_played: int
    locations_played: int
    total_gross_points: int
    total_distance_km: float
    sum_of_positions: int
    round_wins: int
    podiums: int
    best_round_points: int
    best_round_locations: int
    worst_round_points: int
    worst_round_locations: int

    @property
    def avg_points_per_location(self) -> float:
        return self.total_gross_points / self.locations_played

    @property
    def avg_points_per_round(self) -> float:
        return self.total_gross_points / self.rounds_played

    @property
    def avg_position(self) -> float:
        return self.sum_of_positions / self.rounds_played

    @property
    def avg_distance_km(self) -> float:
        return self.total_distance_km / self.locations_played

    @property
    def win_rate(self) -> float:
        return self.round_wins / self.rounds_played


class GrossStatsTable(BaseModel):
    """The full table plus the context needed to caveat it."""

    players: list[PlayerGrossStats]
    rounds_counted: int
    leagues_counted: int
    first_round_date: date | None = None
    last_round_date: date | None = None

    def sorted_by(self, key: SortKey) -> list[PlayerGrossStats]:
        sort_keys = {
            SortKey.POINTS_PER_LOCATION: lambda p: -p.avg_points_per_location,
            SortKey.AVERAGE_POSITION: lambda p: p.avg_position,
            SortKey.TOTAL_POINTS: lambda p: -p.total_gross_points,
            SortKey.ROUND_WINS: lambda p: (-p.round_wins, -p.win_rate),
        }
        return sorted(self.players, key=sort_keys[key])


class _Accumulator:
    """Mutable running totals for one player, frozen into PlayerGrossStats at the end."""

    def __init__(self, player: str):
        self.player = player
        self.rounds_played = 0
        self.locations_played = 0
        self.total_gross_points = 0
        self.total_distance_km = 0.0
        self.sum_of_positions = 0
        self.round_wins = 0
        self.podiums = 0
        self.best_round: tuple[int, int] | None = None
        self.worst_round: tuple[int, int] | None = None

    def add_round(
        self, points: int, locations: int, distance_km: float, position: int
    ) -> None:
        self.rounds_played += 1
        self.locations_played += locations
        self.total_gross_points += points
        self.total_distance_km += distance_km
        self.sum_of_positions += position

        if position == 1:
            self.round_wins += 1
        if position <= 3:
            self.podiums += 1

        # Compare on points-per-location so 5- and 10-location rounds are comparable.
        rate = points / locations
        if self.best_round is None or rate > self.best_round[0] / self.best_round[1]:
            self.best_round = (points, locations)
        if self.worst_round is None or rate < self.worst_round[0] / self.worst_round[1]:
            self.worst_round = (points, locations)

    def freeze(self) -> PlayerGrossStats:
        return PlayerGrossStats(
            player=self.player,
            rounds_played=self.rounds_played,
            locations_played=self.locations_played,
            total_gross_points=self.total_gross_points,
            total_distance_km=self.total_distance_km,
            sum_of_positions=self.sum_of_positions,
            round_wins=self.round_wins,
            podiums=self.podiums,
            best_round_points=self.best_round[0],
            best_round_locations=self.best_round[1],
            worst_round_points=self.worst_round[0],
            worst_round_locations=self.worst_round[1],
        )


def canonical_name(player: str) -> str:
    return NAME_CHANGES.get(player, player)


def locations_in_round(result: ChallengeResult) -> int:
    """How many locations the round was played over.

    Prefers the recorded challenge settings; older league files predate that
    field, so fall back to the most locations anyone actually guessed.
    """
    if result.challenge_settings is not None:
        return result.challenge_settings.number_of_locations
    return max((len(score.guesses) for score in result.scores), default=0)


def finishers(result: ChallengeResult) -> list[ChallengeScore]:
    """Scores for players who guessed every location in the round.

    Deliberately not ChallengeScore.is_finished: that trusts a per-score
    num_rounds field which defaults to 10 and is absent from older league files.
    """
    locations = locations_in_round(result)
    if locations == 0:
        return []
    return [score for score in result.scores if len(score.guesses) == locations]


def load_finished_rounds(
    finished_league_dir: Path,
) -> list[tuple[ChallengeResult, date | None]]:
    """Every round from every finished league, paired with its best-known date."""
    rounds: list[tuple[ChallengeResult, date | None]] = []

    for league_file in sorted(finished_league_dir.glob("league_*.json")):
        try:
            league_start_date = datetime.strptime(
                league_file.stem.split("_")[-1], "%Y%m%d"
            ).date()
        except ValueError:
            league_start_date = None

        with league_file.open("r") as f:
            league_data = json.load(f)

        for index, round_data in enumerate(league_data.get("results", [])):
            round_date = (
                league_start_date + timedelta(days=index) if league_start_date else None
            )
            rounds.append((ChallengeResult(**round_data), round_date))

    return rounds


def compute_gross_stats(
    finished_league_dir: Path,
    min_finishers: int = MIN_FINISHERS_PER_ROUND,
) -> GrossStatsTable:
    """Aggregate handicap-free statistics across every finished league.

    Only players who completed a round are counted for that round, so an
    abandoned attempt neither drags down an average nor flatters anyone else's
    position.
    """
    accumulators: dict[str, _Accumulator] = {}
    rounds_counted = 0
    leagues_counted = len(list(finished_league_dir.glob("league_*.json")))
    round_dates: list[date] = []

    for result, round_date in load_finished_rounds(finished_league_dir):
        completed = finishers(result)
        if len(completed) < min_finishers:
            continue

        locations = locations_in_round(result)
        gross_by_player = {
            canonical_name(score.player.name): score.gross_score for score in completed
        }
        positions = get_ranks_from_scores(gross_by_player)

        for score in completed:
            name = canonical_name(score.player.name)
            accumulator = accumulators.setdefault(name, _Accumulator(name))
            accumulator.add_round(
                points=score.gross_score,
                locations=locations,
                distance_km=sum(guess.distance_km for guess in score.guesses),
                position=positions[name],
            )

        rounds_counted += 1
        if round_date is not None:
            round_dates.append(round_date)

    return GrossStatsTable(
        players=[accumulator.freeze() for accumulator in accumulators.values()],
        rounds_counted=rounds_counted,
        leagues_counted=leagues_counted,
        first_round_date=min(round_dates, default=None),
        last_round_date=max(round_dates, default=None),
    )


def head_to_head(
    finished_league_dir: Path,
    player_a: str,
    player_b: str,
    min_finishers: int = MIN_FINISHERS_PER_ROUND,
) -> dict[str, int]:
    """Rounds where each player out-scored the other, counting only shared rounds."""
    tally = defaultdict(int)
    player_a, player_b = canonical_name(player_a), canonical_name(player_b)

    for result, _ in load_finished_rounds(finished_league_dir):
        completed = finishers(result)
        if len(completed) < min_finishers:
            continue

        gross_by_player = {
            canonical_name(score.player.name): score.gross_score for score in completed
        }
        if player_a not in gross_by_player or player_b not in gross_by_player:
            continue

        if gross_by_player[player_a] > gross_by_player[player_b]:
            tally[player_a] += 1
        elif gross_by_player[player_b] > gross_by_player[player_a]:
            tally[player_b] += 1
        else:
            tally["draw"] += 1

    return dict(tally)


if __name__ == "__main__":
    import sys

    data_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
    table = compute_gross_stats(data_dir / "leagues" / "finished")

    print(
        f"{table.rounds_counted} rounds across {table.leagues_counted} leagues, "
        f"handicaps ignored\n"
    )
    header = f"{'player':<32}{'pts/loc':>9}{'avg pos':>9}{'wins':>6}{'rounds':>8}{'total':>10}"
    print(header)
    print("-" * len(header))
    for stats in table.sorted_by(SortKey.POINTS_PER_LOCATION):
        print(
            f"{stats.player:<32}"
            f"{stats.avg_points_per_location:>9,.0f}"
            f"{stats.avg_position:>9.2f}"
            f"{stats.round_wins:>6}"
            f"{stats.rounds_played:>8}"
            f"{stats.total_gross_points:>10,}"
        )
