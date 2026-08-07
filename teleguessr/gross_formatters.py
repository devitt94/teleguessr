"""Telegram message formatting for the handicap-free stats table."""

from teleguessr.gross_stats import GrossStatsTable, PlayerGrossStats, SortKey


TELEGRAM_MAX_MESSAGE_LENGTH = 4096

SORT_LABELS = {
    SortKey.POINTS_PER_LOCATION: "average points per location",
    SortKey.AVERAGE_POSITION: "average finishing position",
    SortKey.TOTAL_POINTS: "total gross points",
    SortKey.ROUND_WINS: "round wins",
}

RANK_EMOJI = {1: "🥇", 2: "🥈", 3: "🥉"}


def format_gross_stats_html(
    table: GrossStatsTable,
    sort_key: SortKey = SortKey.POINTS_PER_LOCATION,
) -> str:
    if not table.players:
        return (
            "📊 <b>All-Time Gross Stats</b>\n\n"
            "No completed rounds found yet — nothing to report."
        )

    date_range = ""
    if table.first_round_date and table.last_round_date:
        date_range = (
            f" ({table.first_round_date:%b %Y} – {table.last_round_date:%b %Y})"
        )

    header = (
        "📊 <b>All-Time Gross Stats</b> — no handicaps, just raw points\n"
        f"<i>{table.rounds_counted} completed rounds across "
        f"{table.leagues_counted} leagues{date_range}. "
        f"Sorted by {SORT_LABELS[sort_key]}.</i>\n"
    )

    blocks = [header]
    for position, stats in enumerate(table.sorted_by(sort_key), start=1):
        blocks.append(format_player_block(position, stats))

    blocks.append(
        "<i>Only rounds a player finished are counted. "
        "Positions are re-ranked on gross score, so they will not match the "
        "net results in /leaderboard.</i>"
    )
    return "\n".join(blocks)


def format_player_block(position: int, stats: PlayerGrossStats) -> str:
    emoji = RANK_EMOJI.get(position, "▪️")
    return (
        f"{emoji} <b>{position}. {stats.player}</b> — "
        f"<b>{stats.avg_points_per_location:,.0f}</b> pts/loc\n"
        f"    • Avg position <b>{stats.avg_position:.2f}</b> · "
        f"Avg round <b>{stats.avg_points_per_round:,.0f}</b>\n"
        f"    • Wins <b>{stats.round_wins}</b> · "
        f"Podiums <b>{stats.podiums}</b> · "
        f"Rounds <b>{stats.rounds_played}</b>\n"
        f"    • Total <b>{stats.total_gross_points:,}</b> · "
        f"Avg miss <b>{stats.avg_distance_km:,.0f} km</b>\n"
    )


def split_message(text: str, limit: int = TELEGRAM_MAX_MESSAGE_LENGTH) -> list[str]:
    """Break a long message on line boundaries so Telegram will accept it."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit and current:
            chunks.append(current)
            current = line
        else:
            current = candidate

    if current:
        chunks.append(current)
    return chunks


def format_head_to_head_html(
    player_a: str, player_b: str, tally: dict[str, int]
) -> str:
    a_wins = tally.get(player_a, 0)
    b_wins = tally.get(player_b, 0)
    draws = tally.get("draw", 0)

    if a_wins + b_wins + draws == 0:
        return f"No shared completed rounds between {player_a} and {player_b}."

    lines = [
        f"⚔️ <b>{player_a}</b> vs <b>{player_b}</b> <i>(gross score, shared rounds)</i>\n",
        f"    • {player_a}: <b>{a_wins}</b>",
        f"    • {player_b}: <b>{b_wins}</b>",
    ]
    if draws:
        lines.append(f"    • Draws: <b>{draws}</b>")
    return "\n".join(lines)
