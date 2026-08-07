"""Deep per-player history assembled from finished leagues, bets and handicaps.

Where gross_stats compares everyone on one axis, this looks at a single player
from every angle worth having: form, splits by weekday and challenge type,
guess quality, league honours, head-to-head records and lifetime betting P&L.

Self-contained apart from read-only imports of the shared models.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from statistics import median

from pydantic import BaseModel

from teleguessr.challenge_settings_generators import (
    CLASSIC_WORLD_MAP_ID,
    COMMUNITY_WORLD_MAP_ID,
    MOVING_WORLD_MAP_ID,
    URBAN_WORLD_MAP_ID,
)
from teleguessr.gross_stats import (
    MIN_FINISHERS_PER_ROUND,
    canonical_name,
    finishers,
    locations_in_round,
)
from teleguessr.models import Bet, BetType, ChallengeResult, ChallengeSettings
from teleguessr.ranks import get_ranks_from_scores


MAP_NAMES = {
    CLASSIC_WORLD_MAP_ID: "Classic World",
    COMMUNITY_WORLD_MAP_ID: "Community World",
    MOVING_WORLD_MAP_ID: "Moving World",
    URBAN_WORLD_MAP_ID: "Urban World",
}

WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

PERFECT_GUESS = 5000
DUD_GUESS_THRESHOLD = 1000
FORM_ROUNDS = 8
# A split needs this many rounds before it says anything about a player.
MIN_ROUNDS_PER_SPLIT = 3
MIN_MEETINGS_FOR_HEAD_TO_HEAD = 5


def round_type_label(settings: ChallengeSettings | None) -> str:
    """A short human label for a challenge's rules, e.g. 'Urban World · 90s · Moving'."""
    if settings is None:
        return "Unknown"

    map_name = MAP_NAMES.get(settings.map_id, "Custom map")
    if not settings.move_allowed and not settings.pan_allowed:
        movement = "NMPZ"
    elif not settings.move_allowed:
        movement = "No move"
    else:
        movement = "Moving"

    return f"{map_name} · {settings.time_limit_seconds}s · {movement}"


class FinishedLeague(BaseModel):
    """One finished league file, with the bits needed for per-round attribution."""

    start_date: date
    rounds: list[ChallengeResult]
    final_scores: dict[str, int]

    def round_date(self, round_index: int) -> date:
        return self.start_date + timedelta(days=round_index)

    def final_standings(self) -> list[str]:
        """Players best-to-worst, tie-broken on the last round like the bot does."""
        if not self.final_scores:
            return []

        last_round_net = {}
        if self.rounds:
            last_round_net = {
                canonical_name(score.player.name): score.compute_net_score()
                for score in self.rounds[-1].scores
            }

        return sorted(
            self.final_scores,
            key=lambda player: (
                self.final_scores[player],
                last_round_net.get(player, 0),
            ),
            reverse=True,
        )


class Split(BaseModel):
    """A player's record within one slice of rounds (a weekday, a challenge type)."""

    label: str
    rounds: int
    points: int
    locations: int
    sum_of_positions: int

    @property
    def avg_points_per_location(self) -> float:
        return self.points / self.locations

    @property
    def avg_position(self) -> float:
        return self.sum_of_positions / self.rounds


class HeadToHead(BaseModel):
    opponent: str
    wins: int
    losses: int

    @property
    def meetings(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        return self.wins / self.meetings if self.meetings else 0.0


class BettingRecord(BaseModel):
    bets_placed: int = 0
    total_staked: float = 0.0
    profit_and_loss: float = 0.0
    biggest_win: float = 0.0
    biggest_loss: float = 0.0
    pnl_backing_self: float = 0.0
    bets_on_self: int = 0
    most_backed_runner: str | None = None
    leagues_bet_in: int = 0

    @property
    def roi(self) -> float:
        return self.profit_and_loss / self.total_staked if self.total_staked else 0.0


class PlayerProfile(BaseModel):
    """Everything known about one player."""

    player: str

    rounds_played: int
    leagues_played: int
    first_seen: date | None
    last_seen: date | None

    total_gross_points: int
    locations_played: int
    sum_of_gross_positions: int
    gross_round_wins: int
    gross_podiums: int
    best_round_points: int
    best_round_locations: int
    best_round_date: date | None
    worst_round_points: int
    worst_round_locations: int

    sum_of_net_positions: int
    net_round_wins: int
    net_podiums: int

    league_wins: int
    league_podiums: int
    wooden_spoons: int
    sum_of_league_finishes: int

    perfect_guesses: int
    dud_guesses: int
    zero_guesses: int
    total_guesses: int
    avg_distance_km: float
    median_distance_km: float

    by_weekday: list[Split]
    by_round_type: list[Split]
    recent_form: list[int]

    bunny: HeadToHead | None
    nemesis: HeadToHead | None

    current_handicap: float | None
    min_handicap: float | None
    max_handicap: float | None

    betting: BettingRecord

    @property
    def avg_points_per_location(self) -> float:
        return self.total_gross_points / self.locations_played

    @property
    def avg_points_per_round(self) -> float:
        return self.total_gross_points / self.rounds_played

    @property
    def avg_gross_position(self) -> float:
        return self.sum_of_gross_positions / self.rounds_played

    @property
    def avg_net_position(self) -> float:
        return self.sum_of_net_positions / self.rounds_played

    @property
    def avg_league_finish(self) -> float:
        return self.sum_of_league_finishes / self.leagues_played

    @property
    def perfect_guess_rate(self) -> float:
        return self.perfect_guesses / self.total_guesses

    @property
    def dud_guess_rate(self) -> float:
        return self.dud_guesses / self.total_guesses

    def best_split(self, splits: list[Split]) -> Split | None:
        eligible = [s for s in splits if s.rounds >= MIN_ROUNDS_PER_SPLIT]
        return max(eligible, key=lambda s: s.avg_points_per_location, default=None)

    def worst_split(self, splits: list[Split]) -> Split | None:
        eligible = [s for s in splits if s.rounds >= MIN_ROUNDS_PER_SPLIT]
        return min(eligible, key=lambda s: s.avg_points_per_location, default=None)


class _SplitAccumulator:
    def __init__(self, label: str):
        self.label = label
        self.rounds = 0
        self.points = 0
        self.locations = 0
        self.sum_of_positions = 0

    def add(self, points: int, locations: int, position: int) -> None:
        self.rounds += 1
        self.points += points
        self.locations += locations
        self.sum_of_positions += position

    def freeze(self) -> Split:
        return Split(
            label=self.label,
            rounds=self.rounds,
            points=self.points,
            locations=self.locations,
            sum_of_positions=self.sum_of_positions,
        )


def load_finished_leagues(finished_league_dir: Path) -> list[FinishedLeague]:
    leagues: list[FinishedLeague] = []
    if not finished_league_dir.exists():
        return leagues

    for league_file in sorted(finished_league_dir.glob("league_*.json")):
        try:
            start_date = datetime.strptime(
                league_file.stem.split("_")[-1], "%Y%m%d"
            ).date()
        except ValueError:
            continue

        with league_file.open("r") as f:
            data = json.load(f)

        leagues.append(
            FinishedLeague(
                start_date=start_date,
                rounds=[ChallengeResult(**r) for r in data.get("results", [])],
                final_scores={
                    canonical_name(player): score
                    for player, score in (data.get("scores") or {}).items()
                },
            )
        )

    return leagues


def list_players(data_dir: Path) -> list[str]:
    """Every player who has ever completed a round, alphabetically."""
    players: set[str] = set()
    for league in load_finished_leagues(data_dir / "leagues" / "finished"):
        for result in league.rounds:
            for score in result.scores:
                players.add(canonical_name(score.player.name))
    return sorted(players)


def resolve_player(data_dir: Path, query: str) -> list[str]:
    """Match a free-text query against known players, exact first then substring."""
    players = list_players(data_dir)
    needle = query.strip().lower()
    if not needle:
        return players

    exact = [p for p in players if p.lower() == needle]
    if exact:
        return exact

    return [p for p in players if needle in p.lower()]


def load_handicap_history(data_dir: Path) -> dict[str, list[float]]:
    """Every recorded handicap per player, oldest file first."""
    history: dict[str, list[float]] = defaultdict(list)
    handicaps_dir = data_dir / "handicaps"
    if not handicaps_dir.exists():
        return history

    for handicap_file in sorted(handicaps_dir.glob("*.json")):
        try:
            with handicap_file.open("r") as f:
                handicaps = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        for player, handicap in handicaps.items():
            history[canonical_name(player)].append(handicap)

    return history


def compute_betting_record(
    data_dir: Path, player: str, leagues: list[FinishedLeague]
) -> BettingRecord:
    """Lifetime betting P&L, settled the same way the bot settles it.

    The bot pays out every market against the net league winner, so this
    mirrors that rather than settling podium/wooden-spoon markets separately --
    the aim is the money players actually won and lost.
    """
    record = BettingRecord()
    bets_dir = data_dir / "bets"
    if not bets_dir.exists():
        return record

    runner_stakes: dict[str, float] = defaultdict(float)

    for league in leagues:
        standings = league.final_standings()
        if not standings:
            continue
        winner = standings[0]

        bets_file = bets_dir / f"bets_{league.start_date.strftime('%Y%m%d')}.json"
        if not bets_file.exists():
            continue

        try:
            with bets_file.open("r") as f:
                bets = [Bet(**bet) for bet in json.load(f)]
        except (json.JSONDecodeError, OSError, TypeError):
            continue

        player_bets = [b for b in bets if canonical_name(b.bettor) == player]
        if not player_bets:
            continue

        record.leagues_bet_in += 1

        for bet in player_bets:
            runner = canonical_name(bet.runner)
            won = (runner == winner) ^ (bet.bet_type == BetType.LAY)
            pnl = bet.potential_profit if won else -bet.stake

            record.bets_placed += 1
            record.total_staked += bet.stake
            record.profit_and_loss += pnl
            record.biggest_win = max(record.biggest_win, pnl)
            record.biggest_loss = min(record.biggest_loss, pnl)
            runner_stakes[runner] += bet.stake

            if runner == player:
                record.bets_on_self += 1
                record.pnl_backing_self += pnl

    if runner_stakes:
        record.most_backed_runner = max(runner_stakes, key=runner_stakes.get)

    return record


def compute_player_profile(
    data_dir: Path,
    player: str,
    min_finishers: int = MIN_FINISHERS_PER_ROUND,
) -> PlayerProfile | None:
    """Build the full profile, or None if the player has no completed rounds."""
    player = canonical_name(player)
    leagues = load_finished_leagues(data_dir / "leagues" / "finished")

    rounds_played = 0
    leagues_played = 0
    total_points = 0
    locations_played = 0
    sum_gross_positions = 0
    gross_wins = 0
    gross_podiums = 0
    sum_net_positions = 0
    net_wins = 0
    net_podiums = 0
    league_wins = 0
    league_podiums = 0
    wooden_spoons = 0
    sum_league_finishes = 0
    perfect = 0
    duds = 0
    zeros = 0
    distances: list[float] = []
    best: tuple[int, int, date | None] | None = None
    worst: tuple[int, int] | None = None

    weekday_splits: dict[str, _SplitAccumulator] = {}
    type_splits: dict[str, _SplitAccumulator] = {}
    dated_positions: list[tuple[date, int]] = []
    h2h: dict[str, list[int]] = defaultdict(
        lambda: [0, 0]
    )  # opponent -> [wins, losses]

    for league in leagues:
        played_this_league = False

        for round_index, result in enumerate(league.rounds):
            completed = finishers(result)
            if len(completed) < min_finishers:
                continue

            gross_by_player = {
                canonical_name(s.player.name): s.gross_score for s in completed
            }
            if player not in gross_by_player:
                continue

            played_this_league = True
            rounds_played += 1
            locations = locations_in_round(result)
            points = gross_by_player[player]
            position = get_ranks_from_scores(gross_by_player)[player]
            round_date = league.round_date(round_index)

            total_points += points
            locations_played += locations
            sum_gross_positions += position
            gross_wins += position == 1
            gross_podiums += position <= 3
            dated_positions.append((round_date, position))

            # Rank net over the same finisher set as gross, keyed on canonical
            # names, so the two averages are directly comparable and renamed
            # players are not silently dropped.
            net_by_player = {
                canonical_name(s.player.name): s.compute_net_score() for s in completed
            }
            net_position = get_ranks_from_scores(net_by_player)[player]
            sum_net_positions += net_position
            net_wins += net_position == 1
            net_podiums += net_position <= 3

            for opponent, opponent_points in gross_by_player.items():
                if opponent == player or opponent_points == points:
                    continue
                h2h[opponent][0 if points > opponent_points else 1] += 1

            player_score = next(
                s for s in completed if canonical_name(s.player.name) == player
            )
            for guess in player_score.guesses:
                perfect += guess.score == PERFECT_GUESS
                duds += guess.score < DUD_GUESS_THRESHOLD
                zeros += guess.score == 0
                distances.append(guess.distance_km)

            rate = points / locations
            if best is None or rate > best[0] / best[1]:
                best = (points, locations, round_date)
            if worst is None or rate < worst[0] / worst[1]:
                worst = (points, locations)

            weekday = WEEKDAYS[round_date.weekday()]
            weekday_splits.setdefault(weekday, _SplitAccumulator(weekday)).add(
                points, locations, position
            )

            type_label = round_type_label(result.challenge_settings)
            type_splits.setdefault(type_label, _SplitAccumulator(type_label)).add(
                points, locations, position
            )

        if played_this_league:
            leagues_played += 1
            standings = league.final_standings()
            if player in standings:
                finish = standings.index(player) + 1
                sum_league_finishes += finish
                league_wins += finish == 1
                league_podiums += finish <= 3
                wooden_spoons += finish == len(standings)

    if rounds_played == 0:
        return None

    handicap_history = load_handicap_history(data_dir).get(player, [])
    dated_positions.sort()

    meetings = [
        HeadToHead(opponent=opponent, wins=wins, losses=losses)
        for opponent, (wins, losses) in h2h.items()
        if wins + losses >= MIN_MEETINGS_FOR_HEAD_TO_HEAD
    ]

    return PlayerProfile(
        player=player,
        rounds_played=rounds_played,
        leagues_played=leagues_played,
        first_seen=dated_positions[0][0] if dated_positions else None,
        last_seen=dated_positions[-1][0] if dated_positions else None,
        total_gross_points=total_points,
        locations_played=locations_played,
        sum_of_gross_positions=sum_gross_positions,
        gross_round_wins=gross_wins,
        gross_podiums=gross_podiums,
        best_round_points=best[0],
        best_round_locations=best[1],
        best_round_date=best[2],
        worst_round_points=worst[0],
        worst_round_locations=worst[1],
        sum_of_net_positions=sum_net_positions,
        net_round_wins=net_wins,
        net_podiums=net_podiums,
        league_wins=league_wins,
        league_podiums=league_podiums,
        wooden_spoons=wooden_spoons,
        sum_of_league_finishes=sum_league_finishes,
        perfect_guesses=perfect,
        dud_guesses=duds,
        zero_guesses=zeros,
        total_guesses=len(distances),
        avg_distance_km=sum(distances) / len(distances) if distances else 0.0,
        median_distance_km=median(distances) if distances else 0.0,
        by_weekday=[
            weekday_splits[day].freeze() for day in WEEKDAYS if day in weekday_splits
        ],
        by_round_type=[accumulator.freeze() for accumulator in type_splits.values()],
        recent_form=[position for _, position in dated_positions[-FORM_ROUNDS:]],
        bunny=max(meetings, key=lambda m: m.win_rate, default=None),
        nemesis=min(meetings, key=lambda m: m.win_rate, default=None),
        current_handicap=handicap_history[-1] if handicap_history else None,
        min_handicap=min(handicap_history) if handicap_history else None,
        max_handicap=max(handicap_history) if handicap_history else None,
        betting=compute_betting_record(data_dir, player, leagues),
    )
