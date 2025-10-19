from models import RoundResult
from settings import PLAYER_SHORTNAMES


def get_player_shortname(fullname: str) -> str:
    try:
        return PLAYER_SHORTNAMES[fullname]
    except KeyError:
        return f"{fullname[:8]}..."


def format_round_result(result: RoundResult) -> str:
    """Format the round result into a readable marked-down table."""
    lines = []

    if not result.scores:
        return "No scores available\!"

    # Sort scores by net score (descending)
    sorted_scores = sorted(result.scores, key=lambda rs: rs.net_score, reverse=True)

    name_width = (
        max(len(get_player_shortname(rs.player.name)) for rs in sorted_scores) + 2
    )
    score_width = 6
    hcap_width = 6
    lines.append(
        f"{'Player'.ljust(name_width)}| {'Gross'.rjust(score_width)} | {'Hcap'.rjust(hcap_width)} | {'Net'.rjust(score_width)}"
    )
    lines.append("-" * (name_width + score_width * 2 + hcap_width + 9))
    for rs in sorted_scores:
        lines.append(
            f"{get_player_shortname(rs.player.name).ljust(name_width)}| "
            f"{str(rs.gross_score).rjust(score_width)} | "
            f"{str(rs.player.round_hcap).rjust(6)} | "
            f"{str(rs.net_score).rjust(score_width)}"
        )
    table = "```\n" + "\n".join(lines) + "\n```"
    return table


def format_scoreboard(scores: dict, header: str = "Total Score") -> str:
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    if not sorted_scores:
        return "No scores available\!"

    # Determine column widths
    name_width = max(len(name) for name, _ in sorted_scores) + 2
    score_width = 10

    lines = [
        f"{'Player'.ljust(name_width)}| {header.rjust(score_width)}",
        "-" * (name_width + score_width + 2),
    ]
    for name, score in sorted_scores:
        lines.append(f"{name.ljust(name_width)}| {str(score).rjust(score_width)}")

    table = "```\n" + "\n".join(lines) + "\n```"
    return table
