"""Telegram formatting for the per-player profile."""

from teleguessr.formatters import get_position_str
from teleguessr.player_stats import PlayerProfile, Split


def format_player_profile_html(profile: PlayerProfile) -> str:
    sections = [
        _header(profile),
        _scoring(profile),
        _positions(profile),
        _honours(profile),
        _guess_quality(profile),
        _splits(profile),
        _rivalries(profile),
        _betting(profile),
        _form(profile),
    ]
    return "\n".join(section for section in sections if section)


def _header(profile: PlayerProfile) -> str:
    span = ""
    if profile.first_seen and profile.last_seen:
        span = f" · {profile.first_seen:%b %Y} – {profile.last_seen:%b %Y}"

    return (
        f"👤 <b>{profile.player}</b>\n"
        f"<i>{profile.rounds_played} rounds across "
        f"{profile.leagues_played} leagues{span}</i>\n"
    )


def _scoring(profile: PlayerProfile) -> str:
    best = profile.best_round_points / profile.best_round_locations
    worst = profile.worst_round_points / profile.worst_round_locations
    best_date = (
        f" on {profile.best_round_date:%d %b %Y}" if profile.best_round_date else ""
    )

    return (
        "🎯 <b>Scoring</b> <i>(gross, no handicap)</i>\n"
        f"    • Avg per location: <b>{profile.avg_points_per_location:,.0f}</b>\n"
        f"    • Avg per round: <b>{profile.avg_points_per_round:,.0f}</b>\n"
        f"    • Best round: <b>{best:,.0f}</b>/loc{best_date}\n"
        f"    • Worst round: <b>{worst:,.0f}</b>/loc\n"
        f"    • Lifetime points: <b>{profile.total_gross_points:,}</b>\n"
    )


def _positions(profile: PlayerProfile) -> str:
    return (
        "📊 <b>Finishing positions</b>\n"
        f"    • Avg gross position: <b>{profile.avg_gross_position:.2f}</b>\n"
        f"    • Avg net position: <b>{profile.avg_net_position:.2f}</b>\n"
        f"    • Round wins: <b>{profile.gross_round_wins}</b> gross / "
        f"<b>{profile.net_round_wins}</b> net\n"
        f"    • Round podiums: <b>{profile.gross_podiums}</b> gross / "
        f"<b>{profile.net_podiums}</b> net\n"
    )


def _honours(profile: PlayerProfile) -> str:
    handicap = ""
    if profile.current_handicap is not None:
        handicap = (
            f"    • Handicap now <b>{profile.current_handicap:.0%}</b> "
            f"(range {profile.min_handicap:.0%}–{profile.max_handicap:.0%})\n"
        )

    return (
        "🏆 <b>League honours</b>\n"
        f"    • Titles: <b>{profile.league_wins}</b> · "
        f"Podiums: <b>{profile.league_podiums}</b> · "
        f"Spoons: <b>{profile.wooden_spoons}</b>\n"
        f"    • Avg league finish: <b>{profile.avg_league_finish:.2f}</b>\n"
        f"{handicap}"
    )


def _guess_quality(profile: PlayerProfile) -> str:
    return (
        "🌍 <b>Guess quality</b>\n"
        f"    • 5000s: <b>{profile.perfect_guesses}</b> "
        f"({profile.perfect_guess_rate:.1%} of guesses)\n"
        f"    • Under 1000: <b>{profile.dud_guesses}</b> "
        f"({profile.dud_guess_rate:.1%}) · Zeros: <b>{profile.zero_guesses}</b>\n"
        f"    • Avg miss: <b>{profile.avg_distance_km:,.0f} km</b> · "
        f"Median <b>{profile.median_distance_km:,.0f} km</b>\n"
    )


def _describe_split(split: Split) -> str:
    return (
        f"{split.label} (<b>{split.avg_points_per_location:,.0f}</b>/loc "
        f"over {split.rounds})"
    )


def _splits(profile: PlayerProfile) -> str:
    lines = []

    best_day = profile.best_split(profile.by_weekday)
    worst_day = profile.worst_split(profile.by_weekday)
    if best_day and worst_day and best_day.label != worst_day.label:
        lines.append(f"    • Best day: {_describe_split(best_day)}")
        lines.append(f"    • Worst day: {_describe_split(worst_day)}")

    best_type = profile.best_split(profile.by_round_type)
    worst_type = profile.worst_split(profile.by_round_type)
    if best_type and worst_type and best_type.label != worst_type.label:
        lines.append(f"    • Best format: {_describe_split(best_type)}")
        lines.append(f"    • Worst format: {_describe_split(worst_type)}")

    if not lines:
        return ""

    return "🗓 <b>Splits</b>\n" + "\n".join(lines) + "\n"


def _rivalries(profile: PlayerProfile) -> str:
    if not profile.bunny or not profile.nemesis:
        return ""
    if profile.bunny.opponent == profile.nemesis.opponent:
        return ""

    return (
        "⚔️ <b>Rivalries</b> <i>(gross, shared rounds)</i>\n"
        f"    • Owns: <b>{profile.bunny.opponent}</b> "
        f"({profile.bunny.wins}-{profile.bunny.losses}, "
        f"{profile.bunny.win_rate:.0%})\n"
        f"    • Owned by: <b>{profile.nemesis.opponent}</b> "
        f"({profile.nemesis.wins}-{profile.nemesis.losses}, "
        f"{profile.nemesis.win_rate:.0%})\n"
    )


def _betting(profile: PlayerProfile) -> str:
    betting = profile.betting
    if not betting.bets_placed:
        return "💰 <b>Betting</b>\n    • No bets on record\n"

    sign = "+" if betting.profit_and_loss >= 0 else "−"
    verdict = "up" if betting.profit_and_loss >= 0 else "down"
    self_sign = "+" if betting.pnl_backing_self >= 0 else "−"

    return (
        "💰 <b>Betting</b> <i>(lifetime)</i>\n"
        f"    • P&amp;L: <b>{sign}€{abs(betting.profit_and_loss):,.2f}</b> "
        f"({verdict} on {betting.bets_placed} bets, ROI {betting.roi:+.1%})\n"
        f"    • Staked: <b>€{betting.total_staked:,.2f}</b> across "
        f"{betting.leagues_bet_in} leagues\n"
        f"    • Best: <b>+€{betting.biggest_win:,.2f}</b> · "
        f"Worst: <b>−€{abs(betting.biggest_loss):,.2f}</b>\n"
        f"    • Backing themselves: <b>{self_sign}€"
        f"{abs(betting.pnl_backing_self):,.2f}</b> on {betting.bets_on_self} bets\n"
        f"    • Most backed: <b>{betting.most_backed_runner}</b>\n"
    )


def _form(profile: PlayerProfile) -> str:
    if not profile.recent_form:
        return ""
    form = "-".join(get_position_str(position) for position in profile.recent_form)
    return f"📈 <b>Recent form</b> <i>(gross, oldest first)</i>\n    • {form}\n"


def format_player_list_html(players: list[str]) -> str:
    if not players:
        return "No players found — no finished leagues on record yet."
    return f"👥 <b>Pick a player</b> <i>({len(players)} on record)</i>"
