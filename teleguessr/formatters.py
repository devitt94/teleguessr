from datetime import date, datetime

from teleguessr.league import skewed_ranking_score_manager
from teleguessr.models import (
    AbbreviatedRoundScore,
    ChallengeResult,
    ChallengeSettings,
    RankedGuess,
)
from teleguessr.odds import FractionalOdds


NUMBER_EMOJI_MAP = {
    1: "1️⃣",
    2: "2️⃣",
    3: "3️⃣",
    4: "4️⃣",
    5: "5️⃣",
    6: "6️⃣",
    7: "7️⃣",
    8: "8️⃣",
    9: "9️⃣",
    10: "🔟",
}


def get_rank_emoji(position: int, total_participants: int) -> str:
    rank_emojis = {1: "🦈", 2: "🥈", 3: "🥉"}
    rank_emojis[total_participants] = "🐡"
    return rank_emojis.get(position, "🐟")


def format_leaderboard_html(
    leaderboard: dict[int, list[str]],
    scores: dict[str, int],
    best_guesses: dict[str, int],
    worst_guesses: dict[str, int],
    round_positions: dict[str, dict[str, int]],
    rounds_played: int,
) -> str:
    blocks = []
    num_players = len(scores)
    for position, players in leaderboard.items():
        rank_emoji = get_rank_emoji(position, num_players)
        pos_str = get_position_str(position, tied=len(players) > 1)

        for player in players:
            round_results = []
            player_round_positions: dict[str, int] = round_positions.get(player, {})
            for round_index in range(1, rounds_played + 1):
                round_rank = player_round_positions.get(str(round_index), -1)
                round_results.append(get_position_str(round_rank))

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

    # Handle special cases for 11th, 12th, 13th
    if 10 <= position % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(position % 10, "th")

    pos_str = f"{position}{suffix}"
    if tied:
        pos_str = f"={pos_str}"
    return pos_str


def format_awards_html(ranked_guesses: list[RankedGuess]) -> str:
    def format_guess(ranked_guess: RankedGuess) -> str:
        return (
            f"   • Player: {ranked_guess.player.name}\n"
            f"   • Location: <b>{ranked_guess.location_index}</b>\n"
            f"   • Distance: <b>{ranked_guess.guess.distance_km:.2f} km</b>\n"
            f"   • Points: <b>{ranked_guess.guess.score} pts</b>\n"
            f"   • Guess Rating: <b>{ranked_guess.adjusted_score:.1f}</b>\n"
        )

    return (
        f"🐐 <b>Best Guess Award</b>\n{format_guess(ranked_guesses[0])}\n"
        f"🎣 <b>Worst Guess Award</b>\n{format_guess(ranked_guesses[-1])}"
    )


def format_round_result_html(
    result: ChallengeResult,
    ranked_guesses: list[RankedGuess],
) -> str:
    if not result.scores:
        return "⚠️ No scores available!"

    rank_scores = skewed_ranking_score_manager(result)

    sorted_player_scores = sorted(
        result.scores, key=lambda rs: rs.compute_net_score(), reverse=True
    )

    bonus_points = {rs.player.name: 0 for rs in sorted_player_scores}
    best_guess_player = ranked_guesses[0].player.name
    worst_guess_player = ranked_guesses[-1].player.name
    bonus_points[best_guess_player] += 1  # Best Guess bonus
    bonus_points[worst_guess_player] -= 1  # Worst Guess penalty

    num_players = len(sorted_player_scores)

    blocks = []

    for i, rs in enumerate(sorted_player_scores):
        pos = i + 1
        pos_str = get_position_str(pos)

        bonus = bonus_points[rs.player.name]
        rank_points = rank_scores[rs.player.name]
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
            f"    • Hcap Adjustment: <b>{rs.compute_hcap_adjustment()}</b>\n"
            f"    • Net: <b>{rs.compute_net_score()}</b>\n"
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
        return f"{minutes:.0f} minutes" + (
            f" {seconds:.0f} seconds" if seconds > 0 else ""
        )
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours:.0f} hours" + (f" {minutes:.0f} minutes" if minutes > 0 else "")


def format_challenge_settings(challenge_settings: ChallengeSettings) -> str:
    move_str = "Yes" if challenge_settings.move_allowed else "No"
    pan_str = "Yes" if challenge_settings.pan_allowed else "No"
    zoom_str = "Yes" if challenge_settings.zoom_allowed else "No"
    return (
        f"Number of Locations: <b>{challenge_settings.number_of_locations}</b>\n"
        f"Time Limit: <b>{format_time(challenge_settings.time_limit_seconds)}</b>\n"
        f"Move: <b>{move_str}</b>\n"
        f"Pan: <b>{pan_str}</b>\n"
        f"Zoom: <b>{zoom_str}</b>"
    )


def format_datetime_to_time_ago(dt: datetime | date | None) -> str:
    if dt is None:
        return "N/A"
    now = datetime.now()
    if isinstance(dt, date) and not isinstance(dt, datetime):
        dt = datetime.combine(dt, datetime.min.time())

    delta = now - dt

    days = delta.days

    years = days // 365
    if years > 0:
        return f"{years} year{'s' if years > 1 else ''} ago"

    months = days // 30
    if months > 0:
        return f"{months} month{'s' if months > 1 else ''} ago"

    if days > 0:
        return f"{days} day{'s' if days > 1 else ''} ago"

    return "today"


def format_guess(ranked_guess: RankedGuess) -> str:
    return f"- {ranked_guess.player.name} - R{ranked_guess.location_index} (guess rating: {ranked_guess.adjusted_score})"


def format_ranked_guesses(ranked_guesses: list[RankedGuess]) -> str:
    """Format a list of ranked guesses into a human-readable string."""
    top_5_guesses = []
    locations_seen_top_5 = set()
    for ranked_guess in ranked_guesses:
        if ranked_guess.location_index not in locations_seen_top_5:
            top_5_guesses.append(ranked_guess)
            locations_seen_top_5.add(ranked_guess.location_index)
        if len(top_5_guesses) >= 5:
            break

    bottom_5_guesses = []
    locations_seen_bottom_5 = set()
    for ranked_guess in reversed(ranked_guesses):
        if ranked_guess.location_index not in locations_seen_bottom_5:
            bottom_5_guesses.append(ranked_guess)
            locations_seen_bottom_5.add(ranked_guess.location_index)
        if len(bottom_5_guesses) >= 5:
            break

    guesses_message = "📊 Current Round Guesses:\n\n"

    guesses_message += "Top 5 guesses:\n"
    for ranked_guess in top_5_guesses:
        guesses_message += f"{format_guess(ranked_guess)}\n"

    guesses_message += "\nBottom 5 guesses:\n"
    for ranked_guess in bottom_5_guesses:
        guesses_message += f"{format_guess(ranked_guess)}\n"

    return guesses_message


def format_signed_amount(amount: float) -> str:
    if amount > 0:
        return f"+€{amount:.2f}"
    elif amount < 0:
        return f"-€{abs(amount):.2f}"
    else:
        return "€0.00"


def format_outcomes_message(
    all_odds: dict[str, FractionalOdds], outcomes_by_winner: dict[str, dict[str, float]]
) -> str:
    bet_outcomes_message = "📊 Bet Outcomes:\n\n"
    for player, current_odds in all_odds.items():
        bet_outcomes_message += f"{player}: (current odds: {current_odds.formatted})\n"
        for bettor, pnl in outcomes_by_winner[player].items():
            bet_outcomes_message += f"    - {bettor}: {format_signed_amount(pnl)}\n"
        bet_outcomes_message += "\n"

    return bet_outcomes_message


def format_odds_message(
    back_odds: dict[str, FractionalOdds],
    lay_odds: dict[str, FractionalOdds],
) -> str:
    if not back_odds:
        return "Odds are not available."
    odds_message = "📊 Current Odds:\n\n"
    for player, odds in back_odds.items():
        if player in lay_odds:
            odds_message += (
                f"- {player}: {odds.formatted} ({lay_odds[player].formatted} to lay)\n"
            )
        else:
            odds_message += f"- {player}: {odds.formatted}\n"

    odds_message += "\n DM me with /bet to place your bets!"
    odds_message += "\n Use /position to check your current betting position."

    return odds_message


def format_round_leaderboard_message(
    scores_hidden: bool,
    players_played: dict[str, AbbreviatedRoundScore | None],
) -> str:
    leaderboard_message = ""
    if not scores_hidden:
        leaderboard_message += "<b>Current rankings for this round:</b>\n"
        for player, abbreviated_score in players_played.items():
            if abbreviated_score is None:
                rank_emoji = "❓"
                net_score_str = ""
            elif not abbreviated_score.is_finished:
                rank_emoji = "⏳"
                net_score_str = f" ({abbreviated_score.net_score} pts, {abbreviated_score.rounds_played}/{abbreviated_score.total_rounds} played)"
            else:
                rank_emoji = NUMBER_EMOJI_MAP.get(abbreviated_score.rank, "❓")
                net_score_str = f" ({abbreviated_score.net_score} pts)"

            leaderboard_message += f"  {rank_emoji}: {player} {net_score_str}\n"

    else:
        leaderboard_message += "- Players who have played this round\n"

        # Sort players by alphabetical order for consistent display
        sorted_players = sorted(players_played.items())

        for player, abbreviated_score in sorted_players:
            if abbreviated_score is None:
                emoji = "❌"
            elif not abbreviated_score.is_finished:
                emoji = "⏳"
            else:
                emoji = "✅"
            leaderboard_message += f"  - {emoji} {player}\n"

    return leaderboard_message
