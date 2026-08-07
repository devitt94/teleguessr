"""Match formats for the Ryder Cup layer, and how each one is scored.

Everything here works on net scores, so handicaps carry into team play exactly
as they do in the league. Singles and cumulative use the league's own net round
score; the pairs formats need per-location detail, so they apply the same
handicap formula at location level.

Pure functions over plain data -- no file access, no bot state.
"""

from enum import StrEnum
import random

from pydantic import BaseModel

from teleguessr.models import MAX_ROUND_SCORE


class RyderFormat(StrEnum):
    FOURBALL = "FOURBALL"
    FOURSOMES = "FOURSOMES"
    CUMULATIVE = "CUMULATIVE"
    SINGLES = "SINGLES"


FORMAT_LABELS = {
    RyderFormat.FOURBALL: "Fourballs",
    RyderFormat.FOURSOMES: "Foursomes",
    RyderFormat.CUMULATIVE: "Cumulative",
    RyderFormat.SINGLES: "Singles",
}

FORMAT_DESCRIPTIONS = {
    RyderFormat.FOURBALL: (
        "Pairs. The better score of the two counts on every location."
    ),
    RyderFormat.FOURSOMES: (
        "Pairs, alternating locations. First player takes locations 1, 3, 5…, "
        "partner takes 2, 4, 6…"
    ),
    RyderFormat.CUMULATIVE: "Whole team. Every net score added together.",
    RyderFormat.SINGLES: "One against one, drawn at random.",
}

# Days 1 and 4 are fourballs, day 2 foursomes, day 3 cumulative, and the final
# day is always singles so the cup stays alive to the end.
DEFAULT_ROUND_FORMATS = {
    1: RyderFormat.FOURBALL,
    2: RyderFormat.FOURSOMES,
    3: RyderFormat.CUMULATIVE,
    4: RyderFormat.FOURBALL,
}

PAIRS_FORMATS = {RyderFormat.FOURBALL, RyderFormat.FOURSOMES}


class RoundEntry(BaseModel):
    """One player's performance in one round, with everything scoring needs."""

    player: str
    handicap: float
    guess_scores: list[int]
    finished: bool
    net_round_score: int

    def net_guess(self, location_index: int) -> float:
        """Handicap-adjusted score for a single location.

        Same shape as the league's round adjustment, applied per location. The
        league caps a round's total adjustment at half the maximum; that cap
        cannot be expressed per location, so it does not apply here. Only the
        pairs formats use this -- singles and cumulative use the capped league
        net score directly.
        """
        if location_index >= len(self.guess_scores):
            return 0.0
        score = self.guess_scores[location_index]
        return score + self.handicap * (MAX_ROUND_SCORE - score)


class Match(BaseModel):
    """One contest within a round: a single, a pair, or the whole team."""

    round_number: int
    match_format: RyderFormat
    side_a: list[str]
    side_b: list[str]
    points: float = 1.0

    @property
    def is_pairs(self) -> bool:
        return self.match_format in PAIRS_FORMATS


class MatchResult(BaseModel):
    match: Match
    side_a_score: float
    side_b_score: float
    side_a_points: float
    side_b_points: float
    forfeit: bool = False

    @property
    def is_tie(self) -> bool:
        return self.side_a_points == self.side_b_points


def format_for_round(round_number: int, num_rounds: int) -> RyderFormat:
    """The final round is always singles; earlier rounds follow the rota."""
    if round_number >= num_rounds:
        return RyderFormat.SINGLES
    return DEFAULT_ROUND_FORMATS.get(round_number, RyderFormat.FOURBALL)


def cumulative_points(team_size: int) -> float:
    """Weight the cumulative day the same as a pairs day, so it cannot dominate."""
    return float(_matches_on_a_pairs_day(team_size))


def _matches_on_a_pairs_day(team_size: int) -> int:
    """Pairs where possible, plus one single if the team size is odd."""
    return team_size // 2 + team_size % 2


def _split_into_sides(players: list[str], rng: random.Random) -> list[list[str]]:
    """Shuffle a team into pairs, leaving at most one player on their own."""
    shuffled = list(players)
    rng.shuffle(shuffled)

    sides = [shuffled[i : i + 2] for i in range(0, len(shuffled) - 1, 2)]
    if len(shuffled) % 2:
        sides.append([shuffled[-1]])
    return sides


def build_matches(
    round_number: int,
    match_format: RyderFormat,
    team_a: list[str],
    team_b: list[str],
    rng: random.Random,
) -> list[Match]:
    """Draw the matches for one round. Deterministic for a given rng state."""
    if match_format == RyderFormat.CUMULATIVE:
        return [
            Match(
                round_number=round_number,
                match_format=match_format,
                side_a=list(team_a),
                side_b=list(team_b),
                points=cumulative_points(min(len(team_a), len(team_b))),
            )
        ]

    if match_format == RyderFormat.SINGLES:
        drawn_a, drawn_b = list(team_a), list(team_b)
        rng.shuffle(drawn_a)
        rng.shuffle(drawn_b)
        return [
            Match(
                round_number=round_number,
                match_format=match_format,
                side_a=[a],
                side_b=[b],
            )
            for a, b in zip(drawn_a, drawn_b)
        ]

    sides_a = _split_into_sides(team_a, rng)
    sides_b = _split_into_sides(team_b, rng)
    return [
        Match(
            round_number=round_number,
            match_format=match_format,
            side_a=side_a,
            side_b=side_b,
        )
        for side_a, side_b in zip(sides_a, sides_b)
    ]


def _side_score(
    side: list[str],
    match_format: RyderFormat,
    entries: dict[str, RoundEntry],
    locations: int,
) -> float:
    present = [entries[player] for player in side if player in entries]
    if not present:
        return 0.0

    if match_format in (RyderFormat.SINGLES, RyderFormat.CUMULATIVE):
        return float(sum(entry.net_round_score for entry in present))

    if match_format == RyderFormat.FOURBALL:
        return sum(
            max(entry.net_guess(location) for entry in present)
            for location in range(locations)
        )

    # Foursomes: partners alternate locations. A lone player covers them all.
    return sum(
        present[location % len(present)].net_guess(location)
        for location in range(locations)
    )


def _side_forfeits(side: list[str], entries: dict[str, RoundEntry]) -> bool:
    """Any player who did not complete the round forfeits their side's match."""
    return any(player not in entries or not entries[player].finished for player in side)


def score_match(
    match: Match, entries: dict[str, RoundEntry], locations: int
) -> MatchResult:
    """Settle one match. Cumulative counts whoever played; matches are forfeited."""
    score_a = _side_score(match.side_a, match.match_format, entries, locations)
    score_b = _side_score(match.side_b, match.match_format, entries, locations)

    forfeit = False
    if match.match_format != RyderFormat.CUMULATIVE:
        a_out = _side_forfeits(match.side_a, entries)
        b_out = _side_forfeits(match.side_b, entries)
        if a_out or b_out:
            forfeit = True
            if a_out and b_out:
                score_a = score_b = 0.0
            elif a_out:
                score_a, score_b = 0.0, 1.0
            else:
                score_a, score_b = 1.0, 0.0

    if score_a > score_b:
        points_a, points_b = match.points, 0.0
    elif score_b > score_a:
        points_a, points_b = 0.0, match.points
    else:
        points_a = points_b = match.points / 2

    return MatchResult(
        match=match,
        side_a_score=score_a,
        side_b_score=score_b,
        side_a_points=points_a,
        side_b_points=points_b,
        forfeit=forfeit,
    )
