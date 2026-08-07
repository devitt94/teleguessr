"""Telegram formatting for the Ryder Cup."""

from teleguessr.ryder_cup import (
    TEAM_A_EMOJI,
    TEAM_A_NAME,
    TEAM_B_EMOJI,
    TEAM_B_NAME,
    RyderCup,
    Standings,
    next_round_number,
)
from teleguessr.ryder_formats import (
    FORMAT_DESCRIPTIONS,
    FORMAT_LABELS,
    Match,
    MatchResult,
    RyderFormat,
    format_for_round,
)


def format_points(points: float) -> str:
    """Half points read better as ½ than as 0.5."""
    whole, half = divmod(points * 2, 2)
    if half:
        return f"{int(whole)}½" if whole else "½"
    return str(int(whole))


def _side(players: list[str]) -> str:
    """Join partners with '+' — several player names already contain '&'."""
    return " + ".join(players)


def format_draw_html(cup: RyderCup) -> str:
    message = (
        f"🏆 <b>Ryder Cup</b> — league of {cup.league_date:%d %b %Y}\n"
        f"<i>{cup.team_size} a side · {format_points(cup.total_points)} points "
        f"on offer · draw seed {cup.seed}</i>\n\n"
        f"{TEAM_A_EMOJI} <b>Team {TEAM_A_NAME}</b>\n"
    )
    message += "".join(f"    • {player}\n" for player in cup.team_a)
    message += f"\n{TEAM_B_EMOJI} <b>Team {TEAM_B_NAME}</b>\n"
    message += "".join(f"    • {player}\n" for player in cup.team_b)

    if cup.sat_out:
        message += (
            f"\n<i>Odd number signed up, so {_side(cup.sat_out)} sits the cup "
            "out — still playing the league as normal.</i>\n"
        )

    message += "\n<b>Formats</b>\n"
    for round_number in range(1, cup.num_rounds + 1):
        match_format = cup.format_in_round(round_number) or format_for_round(
            round_number, cup.num_rounds
        )
        message += f"    • Day {round_number}: {FORMAT_LABELS[match_format]}\n"

    return message


def format_scoreboard_line(standings: Standings) -> str:
    return (
        f"{TEAM_A_EMOJI} <b>{TEAM_A_NAME} "
        f"{format_points(standings.team_a_points)}</b>"
        f" — <b>{format_points(standings.team_b_points)} {TEAM_B_NAME}</b> "
        f"{TEAM_B_EMOJI}"
    )


def format_standings_html(standings: Standings) -> str:
    cup = standings.cup
    message = (
        f"🏆 <b>Ryder Cup</b> — day {standings.rounds_completed} of "
        f"{cup.num_rounds}\n\n{format_scoreboard_line(standings)}\n"
    )

    if standings.is_decided:
        winner = standings.winner
        if winner is None:
            message += "\n<i>The cup finished level and is shared.</i>\n"
        else:
            message += f"\n🎉 <b>Team {winner} wins the cup!</b>\n"
    else:
        message += (
            f"\n<i>{format_points(standings.points_to_win)} to win · "
            f"{format_points(standings.points_remaining)} still to play for.</i>\n"
        )

    if standings.rounds:
        message += "\n<b>By day</b>\n"
        for round_standings in standings.rounds:
            message += (
                f"    • Day {round_standings.round_number} "
                f"({FORMAT_LABELS[round_standings.match_format]}): "
                f"<b>{format_points(round_standings.team_a_points)}–"
                f"{format_points(round_standings.team_b_points)}</b>\n"
            )

    upcoming = next_round_number(standings)
    if upcoming is not None:
        message += "\n" + format_round_preview_html(cup, upcoming)

    return message


def format_round_preview_html(cup: RyderCup, round_number: int) -> str:
    matches = cup.matches_in_round(round_number)
    if not matches:
        return ""

    match_format = matches[0].match_format
    message = (
        f"📋 <b>Day {round_number}: {FORMAT_LABELS[match_format]}</b>\n"
        f"<i>{FORMAT_DESCRIPTIONS[match_format]}</i>\n"
    )

    if match_format == RyderFormat.CUMULATIVE:
        message += (
            f"    • Whole team, worth {format_points(matches[0].points)} points\n"
        )
        return message

    for match in matches:
        message += f"    • {_side(match.side_a)} <b>v</b> {_side(match.side_b)}\n"

    return message


def _format_match_result(result: MatchResult) -> str:
    match: Match = result.match

    if result.side_a_points > result.side_b_points:
        marker = TEAM_A_EMOJI
    elif result.side_b_points > result.side_a_points:
        marker = TEAM_B_EMOJI
    else:
        marker = "⚪️"

    if match.match_format == RyderFormat.CUMULATIVE:
        contest = f"Team {TEAM_A_NAME} v Team {TEAM_B_NAME}"
    else:
        contest = f"{_side(match.side_a)} v {_side(match.side_b)}"

    scores = f"{result.side_a_score:,.0f}–{result.side_b_score:,.0f}"
    if result.forfeit:
        scores = "forfeit"

    return (
        f"    {marker} {contest}\n"
        f"        <b>{format_points(result.side_a_points)}–"
        f"{format_points(result.side_b_points)}</b> <i>({scores})</i>\n"
    )


def format_scorecard_html(standings: Standings) -> str:
    if not standings.rounds:
        return (
            "🏆 <b>Ryder Cup</b>\n\nNo rounds have been played yet — the card is empty."
        )

    message = f"🏆 <b>Ryder Cup scorecard</b>\n\n{format_scoreboard_line(standings)}\n"

    for round_standings in standings.rounds:
        message += (
            f"\n<b>Day {round_standings.round_number} — "
            f"{FORMAT_LABELS[round_standings.match_format]}</b> "
            f"({format_points(round_standings.team_a_points)}–"
            f"{format_points(round_standings.team_b_points)})\n"
        )
        for result in round_standings.results:
            message += _format_match_result(result)

    return message


def format_signup_html(opted_in: list[str]) -> str:
    message = (
        "🏆 <b>Ryder Cup sign-up</b>\n"
        "<i>Teams are drawn at random from whoever is in. "
        "You must already be playing the league.</i>\n"
    )
    if opted_in:
        message += f"\n<b>In so far ({len(opted_in)})</b>\n"
        message += "".join(f"    • {player}\n" for player in opted_in)
    return message
