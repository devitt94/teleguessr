from models import RoundResult
from settings import PLAYER_SHORTNAMES


def get_player_shortname(fullname: str) -> str:
    try:
        return PLAYER_SHORTNAMES[fullname]
    except KeyError:
        return f"{fullname[:7]}..."


def format_round_result(result: RoundResult) -> str:
    """Format the round result into a readable marked-down table."""
    lines = []

    if not result.scores:
        return "No scores available!"

    # Sort scores by net score (descending)
    sorted_scores = sorted(result.scores, key=lambda rs: rs.net_score, reverse=True)
    name_width = (
        max(len(get_player_shortname(rs.player.name)) for rs in sorted_scores) + 1
    )
    score_width = 5
    bonus_points = {rs.player.name: 0 for rs in sorted_scores}
    points_width = 2
    if result.awards is not None:
        bonus_points[result.awards.best_guess.player.name] += 1
        bonus_points[result.awards.worst_guess.player.name] -= 1

    lines.append(
        f"{'Player'.ljust(name_width)}| {'Gross'.rjust(score_width)} | {'Net'.rjust(score_width)} | RP | BP | TP"
    )

    lines.append("-" * (name_width + score_width * 2 + points_width * 3 + 15))
    num_players = len(sorted_scores)
    for i, rs in enumerate(sorted_scores):
        bonus_points_value = bonus_points[rs.player.name]
        rank_points = num_players - i
        lines.append(
            f"{get_player_shortname(rs.player.name).ljust(name_width)}| "
            f"{str(rs.gross_score).rjust(score_width)} | "
            f"{str(rs.net_score).rjust(score_width)} | "
            f"{str(rank_points).rjust(points_width)} | "
            f"{str(bonus_points_value).rjust(points_width)} | "
            f"{str(bonus_points_value + rank_points).rjust(points_width)}"
        )
    table = "```\n" + "\n".join(lines) + "\n```"
    return table


def format_scoreboard(scores: dict, header: str = "Total Score") -> str:
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    if not sorted_scores:
        return "No scores available!"

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
