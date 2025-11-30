from models import Awards, ChallengeResult, RankedGuess
from settings import PLAYER_SHORTNAMES


def get_player_shortname(fullname: str) -> str:
    try:
        return PLAYER_SHORTNAMES[fullname]
    except KeyError:
        return f"{fullname[:7]}..."


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


def get_rank_emoji(position: int, total_participants: int) -> str:
    rank_emojis = {1: "🦈", 2: "🥈", 3: "🥉"}
    rank_emojis[total_participants] = "🐡"
    return rank_emojis.get(position, "🐟")


def format_leaderboard_html(
    leaderboard: dict[int, list[str]],
    scores: dict[str, int],
    best_guesses: dict,
    worst_guesses: dict,
    round_positions: dict,
    rounds_played: int,
) -> str:
    
    blocks = []
    num_players = len(scores)
    for position, players in leaderboard.items():
        
        rank_emoji = get_rank_emoji(position, num_players)
        pos_str = get_position_str(position, tied=len(players) > 1)

        for player in players:
            round_results = [] 
            player_round_positions: dict[int, int] = round_positions.get(player, {})
            for round_index in range(1, rounds_played + 1):
                round_rank = player_round_positions.get(round_index, -1)
                round_results.append(
                    get_position_str(round_rank)
                )

            score = scores[player]
            round_result_str = "-".join(round_results)

            bg_count = best_guesses[player]
            wg_count = worst_guesses[player]
            awards_str = f"🐐x{bg_count} 🎣x{wg_count}"

            blocks.append(
                f"{rank_emoji} <b>{pos_str} — {player}</b>\n"
                f"    • Score: <b>{score}</b>\n"
                f"    • Results: <b>{round_result_str}</b>\n"
                f"    • Awards: <b>{awards_str}</b>\n"
            )

    return "\n".join(blocks)

def get_position_str(position: int, tied: bool = False) -> str:
    """Convert a numeric position into its ordinal string representation."""
    if position < 0:
        return "DNF"
    
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(position % 10, "th")
    pos_str = f"{position}{suffix}"
    if tied:
        pos_str = f"={pos_str}"
    return pos_str


def format_awards_html(ranked_guesses: list[RankedGuess]) -> str:
    lines = []
    
    bg = ranked_guesses[0]
    lines.append(
        f"🐐 <b>Best Guess Award</b>\n"
        f"   • Player: {bg.player.name}\n"
        f"   • Distance: <b>{bg.guess.distance_km:.2f} km</b> (Median: {bg.guess_stats.median_distance:.2f} km)\n"
        f"   • Score: <b>{bg.guess.score} pts</b> (Median: {bg.guess_stats.median_pts:.2f} pts)\n"
        f"   • Location: <b>{bg.location_index}</b>"
    )
    wg = ranked_guesses[-1]
    lines.append(
        f"🎣 <b>Worst Guess Award</b>\n"
        f"   • Player: {wg.player.name}\n"
        f"   • Distance: <b>{wg.guess.distance_km:.2f} km</b> (Median: {wg.guess_stats.median_distance:.2f} km)\n"
        f"   • Score: <b>{wg.guess.score} pts</b> (Median: {wg.guess_stats.median_pts:.2f} pts)\n"
        f"   • Location: <b>{wg.location_index}</b>"
    )
    return "\n\n".join(lines)

def format_round_result_html(result: ChallengeResult, ranked_guesses: list[RankedGuess]) -> str:
    if not result.scores:
        return "⚠️ No scores available!"

    sorted_scores = sorted(result.scores, key=lambda rs: rs.net_score, reverse=True)

    bonus_points = {rs.player.name: 0 for rs in sorted_scores}
    best_guess_player = ranked_guesses[0].player.name
    worst_guess_player = ranked_guesses[-1].player.name
    bonus_points[best_guess_player] += 1  # Best Guess bonus
    bonus_points[worst_guess_player] -= 1  # Worst Guess penalty

    num_players = len(sorted_scores)

    blocks = []

    for i, rs in enumerate(sorted_scores):
        pos = i + 1
        pos_str = get_position_str(pos)

        bonus = bonus_points[rs.player.name]
        rank_points = num_players - i
        total_points = rank_points + bonus

        points_str = f"{rank_points}"
        if bonus > 0:
            points_str += f" (+{bonus}) = {total_points}"
        elif bonus < 0:
            points_str += f" ({bonus}) = {total_points}"

        rank_emoji = get_rank_emoji(pos, num_players)

        block = (
            f"{rank_emoji} <b>{pos_str} — {rs.player.name}</b>\n"
            f"    • Gross: <b>{rs.gross_score}</b>\n"
            f"    • Hcap: <b>{rs.player.hcap_multiplier:.1%}</b>\n"
            f"    • Hcap Adjustment: <b>{rs.hcap_adjustment}</b>\n"
            f"    • Net: <b>{rs.net_score}</b>\n"
            f"    • Points: <b>{points_str}</b>\n"
        )

        blocks.append(block)


    blocks.append("-" * 60)
    awards_block = format_awards_html(ranked_guesses)
    blocks.append(awards_block)

    return "\n".join(blocks)


def format_time(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} seconds"
    elif seconds < 3600:
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes} minutes" + (f" {seconds} seconds" if seconds > 0 else "")
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours} hours" + (f" {minutes} minutes" if minutes > 0 else "")

    