"""Ryder Cup state: sign-up, the draw, and standings derived from league data.

Read-only with respect to the league. Team points are computed on demand from
the league file the bot already writes, so nothing here can affect scoring,
handicaps, records or betting. Deleting data/ryder/ removes the whole feature
without a trace.
"""

from datetime import date, datetime
import json
from pathlib import Path
import random

from pydantic import BaseModel, Field

from teleguessr.gross_stats import canonical_name, locations_in_round
from teleguessr.models import ChallengeResult
from teleguessr.ryder_formats import (
    FORMAT_LABELS,
    Match,
    MatchResult,
    RoundEntry,
    RyderFormat,
    build_matches,
    format_for_round,
    score_match,
)


TEAM_A_NAME = "Blue"
TEAM_B_NAME = "Red"
TEAM_A_EMOJI = "🔵"
TEAM_B_EMOJI = "🔴"

SIGNUP_FILENAME = "signup.json"


class RyderSignup(BaseModel):
    opted_in: list[str] = Field(default_factory=list)

    def add(self, player: str) -> bool:
        """Returns True if this is a new sign-up."""
        if player in self.opted_in:
            return False
        self.opted_in.append(player)
        return True


class RyderCup(BaseModel):
    """A drawn cup: two teams and every match for every round."""

    league_date: date
    num_rounds: int
    seed: int
    team_a: list[str]
    team_b: list[str]
    sat_out: list[str] = Field(default_factory=list)
    matches: list[Match] = Field(default_factory=list)

    @property
    def team_size(self) -> int:
        return len(self.team_a)

    @property
    def total_points(self) -> float:
        return sum(match.points for match in self.matches)

    def team_of(self, player: str) -> str | None:
        if player in self.team_a:
            return TEAM_A_NAME
        if player in self.team_b:
            return TEAM_B_NAME
        return None

    def matches_in_round(self, round_number: int) -> list[Match]:
        return [m for m in self.matches if m.round_number == round_number]

    def format_in_round(self, round_number: int) -> RyderFormat | None:
        matches = self.matches_in_round(round_number)
        return matches[0].match_format if matches else None


class RoundStandings(BaseModel):
    round_number: int
    match_format: RyderFormat
    results: list[MatchResult]

    @property
    def team_a_points(self) -> float:
        return sum(result.side_a_points for result in self.results)

    @property
    def team_b_points(self) -> float:
        return sum(result.side_b_points for result in self.results)


class Standings(BaseModel):
    cup: RyderCup
    rounds: list[RoundStandings]
    team_a_net_total: int = 0
    team_b_net_total: int = 0

    @property
    def team_a_points(self) -> float:
        return sum(r.team_a_points for r in self.rounds)

    @property
    def team_b_points(self) -> float:
        return sum(r.team_b_points for r in self.rounds)

    @property
    def rounds_completed(self) -> int:
        return len(self.rounds)

    @property
    def points_remaining(self) -> float:
        return self.cup.total_points - self.team_a_points - self.team_b_points

    @property
    def points_to_win(self) -> float:
        """More than half the points on offer."""
        return self.cup.total_points / 2

    @property
    def is_decided(self) -> bool:
        lead = abs(self.team_a_points - self.team_b_points)
        return self.points_remaining == 0 or lead > self.points_remaining

    @property
    def leader(self) -> str | None:
        if self.team_a_points > self.team_b_points:
            return TEAM_A_NAME
        if self.team_b_points > self.team_a_points:
            return TEAM_B_NAME
        return None

    @property
    def winner(self) -> str | None:
        """Decided cups only. Level cups fall back to aggregate net score.

        The real Ryder Cup lets the holder retain a drawn cup, which cannot
        work here because the teams are redrawn every league. Aggregate net
        score across the cup is the tie-break instead.
        """
        if not self.is_decided:
            return None
        if self.leader is not None:
            return self.leader
        if self.team_a_net_total != self.team_b_net_total:
            return (
                TEAM_A_NAME
                if self.team_a_net_total > self.team_b_net_total
                else TEAM_B_NAME
            )
        return None


def ryder_dir(data_dir: Path) -> Path:
    return data_dir / "ryder"


def signup_path(data_dir: Path) -> Path:
    return ryder_dir(data_dir) / SIGNUP_FILENAME


def cup_path(data_dir: Path, league_date: date) -> Path:
    return ryder_dir(data_dir) / f"ryder_{league_date.strftime('%Y%m%d')}.json"


def load_signup(data_dir: Path) -> RyderSignup:
    path = signup_path(data_dir)
    if not path.exists():
        return RyderSignup()
    with path.open("r") as f:
        return RyderSignup(**json.load(f))


def save_signup(data_dir: Path, signup: RyderSignup) -> None:
    path = signup_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(signup.model_dump(), f, indent=2)


def clear_signup(data_dir: Path) -> None:
    signup_path(data_dir).unlink(missing_ok=True)


def save_cup(data_dir: Path, cup: RyderCup) -> None:
    path = cup_path(data_dir, cup.league_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(json.loads(cup.model_dump_json()), f, indent=2)


def load_cup(data_dir: Path, league_date: date) -> RyderCup | None:
    path = cup_path(data_dir, league_date)
    if not path.exists():
        return None
    with path.open("r") as f:
        return RyderCup(**json.load(f))


def find_current_league_file(data_dir: Path) -> Path | None:
    """The active league if one is running, otherwise the most recent finished."""
    active = sorted((data_dir / "leagues" / "active").glob("league_*.json"))
    if active:
        return active[0]

    finished = sorted((data_dir / "leagues" / "finished").glob("league_*.json"))
    return finished[-1] if finished else None


def league_date_from_path(league_file: Path) -> date:
    return datetime.strptime(league_file.stem.split("_")[-1], "%Y%m%d").date()


def load_league_rounds(league_file: Path) -> list[ChallengeResult]:
    with league_file.open("r") as f:
        data = json.load(f)
    return [ChallengeResult(**result) for result in data.get("results", [])]


def draw_cup(
    league_date: date,
    num_rounds: int,
    players: list[str],
    seed: int | None = None,
) -> RyderCup:
    """Split the sign-ups at random into two teams and draw every match.

    An odd sign-up leaves one randomly chosen player out of the cup; they still
    play the league as normal. The seed is stored so the draw can be audited.
    """
    if len(players) < 4:
        raise ValueError("At least four players are needed for a Ryder Cup.")

    seed = random.randrange(1_000_000) if seed is None else seed
    rng = random.Random(seed)

    pool = sorted(canonical_name(player) for player in players)
    rng.shuffle(pool)

    sat_out: list[str] = []
    if len(pool) % 2:
        sat_out.append(pool.pop())

    half = len(pool) // 2
    team_a, team_b = sorted(pool[:half]), sorted(pool[half:])

    matches: list[Match] = []
    for round_number in range(1, num_rounds + 1):
        matches.extend(
            build_matches(
                round_number=round_number,
                match_format=format_for_round(round_number, num_rounds),
                team_a=team_a,
                team_b=team_b,
                rng=rng,
            )
        )

    return RyderCup(
        league_date=league_date,
        num_rounds=num_rounds,
        seed=seed,
        team_a=team_a,
        team_b=team_b,
        sat_out=sorted(sat_out),
        matches=matches,
    )


def build_round_entries(result: ChallengeResult) -> dict[str, RoundEntry]:
    """Everything the formats need from one round, keyed by canonical name."""
    locations = locations_in_round(result)
    entries: dict[str, RoundEntry] = {}

    for score in result.scores:
        name = canonical_name(score.player.name)
        entries[name] = RoundEntry(
            player=name,
            handicap=score.player.hcap_multiplier,
            guess_scores=[guess.score for guess in score.guesses],
            finished=len(score.guesses) == locations and locations > 0,
            net_round_score=score.compute_net_score(),
        )

    return entries


def compute_standings(cup: RyderCup, rounds: list[ChallengeResult]) -> Standings:
    """Score every completed round. Rounds not yet played are simply absent."""
    round_standings: list[RoundStandings] = []
    team_a_net = 0
    team_b_net = 0

    for round_index, result in enumerate(rounds, start=1):
        matches = cup.matches_in_round(round_index)
        if not matches:
            continue

        entries = build_round_entries(result)
        locations = locations_in_round(result)

        round_standings.append(
            RoundStandings(
                round_number=round_index,
                match_format=matches[0].match_format,
                results=[score_match(match, entries, locations) for match in matches],
            )
        )

        for player, entry in entries.items():
            if player in cup.team_a:
                team_a_net += entry.net_round_score
            elif player in cup.team_b:
                team_b_net += entry.net_round_score

    return Standings(
        cup=cup,
        rounds=round_standings,
        team_a_net_total=team_a_net,
        team_b_net_total=team_b_net,
    )


def load_current_standings(data_dir: Path) -> Standings | None:
    """Standings for whichever league is current, or None if no cup is drawn."""
    league_file = find_current_league_file(data_dir)
    if league_file is None:
        return None

    cup = load_cup(data_dir, league_date_from_path(league_file))
    if cup is None:
        return None

    return compute_standings(cup, load_league_rounds(league_file))


def next_round_number(standings: Standings) -> int | None:
    """The round about to be played, or None once the cup is complete."""
    upcoming = standings.rounds_completed + 1
    return upcoming if upcoming <= standings.cup.num_rounds else None


def describe_format(match_format: RyderFormat) -> str:
    return FORMAT_LABELS[match_format]
