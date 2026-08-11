import json
import random
from datetime import date

import pytest

from teleguessr.ryder_cup import (
    TEAM_A_NAME,
    TEAM_B_NAME,
    RyderCup,
    build_round_entries,
    compute_standings,
    draw_cup,
    find_current_league_file,
    load_cup,
    load_current_standings,
    save_cup,
)
from teleguessr.ryder_formats import (
    Match,
    RoundEntry,
    RyderFormat,
    build_matches,
    cumulative_points,
    format_for_round,
    score_match,
)
from teleguessr.ryder_formatters import (
    format_draw_html,
    format_points,
    format_scorecard_html,
    format_standings_html,
)
from teleguessr.models import ChallengeResult


TEAM_A = ["A1", "A2", "A3", "A4"]
TEAM_B = ["B1", "B2", "B3", "B4"]


def entry(player, guesses, handicap=0.0, finished=True, net=None):
    return RoundEntry(
        player=player,
        handicap=handicap,
        guess_scores=guesses,
        finished=finished,
        net_round_score=sum(guesses) if net is None else net,
    )


def make_score(name, guess_scores, hcap=0.0):
    return {
        "player": {"name": name, "hcap_multiplier": hcap},
        "guesses": [{"score": s, "distance_km": float(5000 - s)} for s in guess_scores],
        "num_rounds": len(guess_scores),
    }


def make_round(scores, locations=5):
    return {
        "challenge_url": "https://www.geoguessr.com/challenge/x",
        "scores": scores,
        "challenge_settings": {
            "map_id": "WORLD",
            "time_limit_seconds": 90,
            "pan_allowed": True,
            "zoom_allowed": True,
            "move_allowed": True,
            "number_of_locations": locations,
        },
    }


def write_league(data_dir, date_str, rounds, active=True, num_rounds=5):
    subdir = "active" if active else "finished"
    league_dir = data_dir / "leagues" / subdir
    league_dir.mkdir(parents=True, exist_ok=True)
    (league_dir / f"league_{date_str}.json").write_text(
        json.dumps({"num_rounds": num_rounds, "results": rounds})
    )


# --- formats -----------------------------------------------------------------


def test_final_round_is_always_singles():
    assert format_for_round(5, 5) == RyderFormat.SINGLES
    assert format_for_round(3, 3) == RyderFormat.SINGLES
    assert format_for_round(1, 5) == RyderFormat.FOURBALL
    assert format_for_round(2, 5) == RyderFormat.FOURSOMES
    assert format_for_round(3, 5) == RyderFormat.CUMULATIVE
    assert format_for_round(4, 5) == RyderFormat.FOURBALL


def test_singles_draws_everyone_exactly_once():
    matches = build_matches(5, RyderFormat.SINGLES, TEAM_A, TEAM_B, random.Random(1))

    assert len(matches) == 4
    assert sorted(m.side_a[0] for m in matches) == TEAM_A
    assert sorted(m.side_b[0] for m in matches) == TEAM_B
    assert all(len(m.side_a) == 1 and len(m.side_b) == 1 for m in matches)


def test_pairs_cover_everyone_exactly_once():
    matches = build_matches(1, RyderFormat.FOURBALL, TEAM_A, TEAM_B, random.Random(2))

    assert len(matches) == 2
    assert sorted(p for m in matches for p in m.side_a) == TEAM_A
    assert sorted(p for m in matches for p in m.side_b) == TEAM_B


def test_odd_team_size_gets_pairs_plus_one_single():
    team_a = ["A1", "A2", "A3", "A4", "A5"]
    team_b = ["B1", "B2", "B3", "B4", "B5"]

    matches = build_matches(1, RyderFormat.FOURBALL, team_a, team_b, random.Random(3))

    assert len(matches) == 3
    assert sorted(len(m.side_a) for m in matches) == [1, 2, 2]
    assert sorted(p for m in matches for p in m.side_a) == team_a


def test_cumulative_is_a_single_match():
    matches = build_matches(3, RyderFormat.CUMULATIVE, TEAM_A, TEAM_B, random.Random(4))

    assert len(matches) == 1
    assert matches[0].side_a == TEAM_A
    assert matches[0].points == 2


@pytest.mark.parametrize("team_size", [4, 5, 6, 7, 8])
def test_cumulative_is_a_flat_two_points_at_any_team_size(team_size):
    """It is one all-or-nothing match, so it must not scale with the roster."""
    assert cumulative_points(team_size) == 2

    pairs_day_matches = len(
        build_matches(
            1,
            RyderFormat.FOURBALL,
            [f"A{i}" for i in range(team_size)],
            [f"B{i}" for i in range(team_size)],
            random.Random(1),
        )
    )
    assert cumulative_points(team_size) <= pairs_day_matches


def test_singles_uses_the_league_net_score():
    match = Match(
        round_number=5, match_format=RyderFormat.SINGLES, side_a=["A1"], side_b=["B1"]
    )
    entries = {
        "A1": entry("A1", [1000] * 5, net=20_000),
        "B1": entry("B1", [4000] * 5, net=19_000),
    }

    result = score_match(match, entries, locations=5)

    assert result.side_a_score == 20_000
    assert result.side_a_points == 1
    assert result.side_b_points == 0


def test_fourball_takes_the_better_score_on_each_location():
    match = Match(
        round_number=1,
        match_format=RyderFormat.FOURBALL,
        side_a=["A1", "A2"],
        side_b=["B1", "B2"],
    )
    entries = {
        "A1": entry("A1", [5000, 0, 5000, 0, 5000]),
        "A2": entry("A2", [0, 5000, 0, 5000, 0]),
        "B1": entry("B1", [3000] * 5),
        "B2": entry("B2", [3000] * 5),
    }

    result = score_match(match, entries, locations=5)

    assert result.side_a_score == 25_000  # best ball is perfect every location
    assert result.side_b_score == 15_000
    assert result.side_a_points == 1


def test_foursomes_alternates_locations_between_partners():
    match = Match(
        round_number=2,
        match_format=RyderFormat.FOURSOMES,
        side_a=["A1", "A2"],
        side_b=["B1", "B2"],
    )
    entries = {
        # A1 covers locations 1, 3, 5 and is perfect; A2 covers 2 and 4 and is not.
        "A1": entry("A1", [5000] * 5),
        "A2": entry("A2", [0] * 5),
        "B1": entry("B1", [2000] * 5),
        "B2": entry("B2", [2000] * 5),
    }

    result = score_match(match, entries, locations=5)

    assert result.side_a_score == 15_000  # three locations from A1, two zeros
    assert result.side_b_score == 10_000


def test_handicaps_apply_to_pairs_formats():
    match = Match(
        round_number=1, match_format=RyderFormat.FOURBALL, side_a=["A1"], side_b=["B1"]
    )
    entries = {
        "A1": entry("A1", [1000] * 5, handicap=0.5),
        "B1": entry("B1", [3000] * 5, handicap=0.0),
    }

    result = score_match(match, entries, locations=5)

    # 1000 + 0.5 * (5000 - 1000) = 3000 per location
    assert result.side_a_score == 15_000
    assert result.side_b_score == 15_000
    assert result.side_a_points == 0.5
    assert result.side_b_points == 0.5


def test_a_tie_splits_the_point():
    match = Match(
        round_number=5, match_format=RyderFormat.SINGLES, side_a=["A1"], side_b=["B1"]
    )
    entries = {
        "A1": entry("A1", [3000] * 5),
        "B1": entry("B1", [3000] * 5),
    }

    result = score_match(match, entries, locations=5)

    assert result.side_a_points == 0.5
    assert result.side_b_points == 0.5
    assert result.is_tie


def test_not_finishing_forfeits_the_match():
    match = Match(
        round_number=5, match_format=RyderFormat.SINGLES, side_a=["A1"], side_b=["B1"]
    )
    entries = {
        "A1": entry("A1", [5000] * 3, finished=False, net=15_000),
        "B1": entry("B1", [1000] * 5, net=5_000),
    }

    result = score_match(match, entries, locations=5)

    assert result.forfeit
    assert result.side_b_points == 1
    assert result.side_a_points == 0


def test_a_missing_player_forfeits_their_side():
    match = Match(
        round_number=1,
        match_format=RyderFormat.FOURBALL,
        side_a=["A1", "A2"],
        side_b=["B1", "B2"],
    )
    entries = {
        "A1": entry("A1", [5000] * 5),
        "B1": entry("B1", [1000] * 5),
        "B2": entry("B2", [1000] * 5),
    }  # A2 never played

    result = score_match(match, entries, locations=5)

    assert result.forfeit
    assert result.side_b_points == 1


def test_both_sides_short_is_a_tie():
    match = Match(
        round_number=5, match_format=RyderFormat.SINGLES, side_a=["A1"], side_b=["B1"]
    )
    entries = {
        "A1": entry("A1", [5000] * 2, finished=False),
        "B1": entry("B1", [1000] * 2, finished=False),
    }

    result = score_match(match, entries, locations=5)

    assert result.forfeit
    assert result.side_a_points == result.side_b_points == 0.5


def test_cumulative_counts_whoever_played_without_forfeits():
    match = Match(
        round_number=3,
        match_format=RyderFormat.CUMULATIVE,
        side_a=["A1", "A2"],
        side_b=["B1", "B2"],
        points=2,
    )
    entries = {
        "A1": entry("A1", [3000] * 5, net=15_000),
        # A2 did not play at all and simply contributes nothing.
        "B1": entry("B1", [1000] * 5, net=5_000),
        "B2": entry("B2", [1000] * 5, net=5_000),
    }

    result = score_match(match, entries, locations=5)

    assert not result.forfeit
    assert result.side_a_score == 15_000
    assert result.side_b_score == 10_000
    assert result.side_a_points == 2


# --- the draw ----------------------------------------------------------------


def test_draw_splits_evenly_and_is_reproducible():
    players = [f"P{i}" for i in range(10)]

    first = draw_cup(date(2025, 1, 6), 5, players, seed=42)
    second = draw_cup(date(2025, 1, 6), 5, players, seed=42)

    assert first.team_a == second.team_a
    assert first.matches == second.matches
    assert len(first.team_a) == len(first.team_b) == 5
    assert sorted(first.team_a + first.team_b) == sorted(players)
    assert first.sat_out == []


def test_odd_sign_up_leaves_one_player_out():
    players = [f"P{i}" for i in range(9)]

    cup = draw_cup(date(2025, 1, 6), 5, players, seed=7)

    assert len(cup.sat_out) == 1
    assert len(cup.team_a) == len(cup.team_b) == 4
    assert sorted(cup.team_a + cup.team_b + cup.sat_out) == sorted(players)


def test_draw_covers_every_round():
    cup = draw_cup(date(2025, 1, 6), 5, [f"P{i}" for i in range(8)], seed=1)

    for round_number in range(1, 6):
        assert cup.matches_in_round(round_number)
    assert cup.format_in_round(5) == RyderFormat.SINGLES


def test_total_points_are_balanced_across_days():
    cup = draw_cup(date(2025, 1, 6), 5, [f"P{i}" for i in range(10)], seed=1)

    # Five a side: 3 fourballs + 3 foursomes + 2 cumulative + 3 fourballs + 5 singles
    assert cup.total_points == 16


def test_draw_needs_four_players():
    with pytest.raises(ValueError):
        draw_cup(date(2025, 1, 6), 5, ["A", "B"], seed=1)


def test_team_lookup():
    cup = draw_cup(date(2025, 1, 6), 5, [f"P{i}" for i in range(8)], seed=1)

    assert cup.team_of(cup.team_a[0]) == TEAM_A_NAME
    assert cup.team_of(cup.team_b[0]) == TEAM_B_NAME
    assert cup.team_of("Nobody") is None


# --- standings ---------------------------------------------------------------


def simple_cup(num_rounds=1):
    return RyderCup(
        league_date=date(2025, 1, 6),
        num_rounds=num_rounds,
        seed=1,
        team_a=["A1", "A2"],
        team_b=["B1", "B2"],
        matches=[
            Match(
                round_number=1,
                match_format=RyderFormat.SINGLES,
                side_a=["A1"],
                side_b=["B1"],
            ),
            Match(
                round_number=1,
                match_format=RyderFormat.SINGLES,
                side_a=["A2"],
                side_b=["B2"],
            ),
        ],
    )


def test_standings_score_completed_rounds_only():
    cup = simple_cup(num_rounds=3)
    rounds = [
        ChallengeResult(
            **make_round(
                [
                    make_score("A1", [4000] * 5),
                    make_score("A2", [4000] * 5),
                    make_score("B1", [1000] * 5),
                    make_score("B2", [1000] * 5),
                ]
            )
        )
    ]

    standings = compute_standings(cup, rounds)

    assert standings.rounds_completed == 1
    assert standings.team_a_points == 2
    assert standings.team_b_points == 0
    assert standings.leader == TEAM_A_NAME


def test_standings_track_aggregate_net_for_the_tie_break():
    cup = simple_cup()
    rounds = [
        ChallengeResult(
            **make_round(
                [
                    make_score("A1", [4000] * 5),
                    make_score("A2", [1000] * 5),
                    make_score("B1", [1000] * 5),
                    make_score("B2", [4000] * 5),
                ]
            )
        )
    ]

    standings = compute_standings(cup, rounds)

    assert standings.team_a_points == standings.team_b_points == 1
    assert standings.team_a_net_total == standings.team_b_net_total == 25_000
    assert standings.leader is None
    assert standings.winner is None  # dead level on both measures -> shared


def test_level_cup_is_broken_by_aggregate_net_score():
    cup = simple_cup()
    rounds = [
        ChallengeResult(
            **make_round(
                [
                    make_score("A1", [4000] * 5),
                    make_score("A2", [1500] * 5),  # loses, but by less
                    make_score("B1", [1000] * 5),
                    make_score("B2", [4000] * 5),
                ]
            )
        )
    ]

    standings = compute_standings(cup, rounds)

    assert standings.team_a_points == standings.team_b_points == 1
    assert standings.is_decided
    assert standings.winner == TEAM_A_NAME


def test_cup_is_decided_once_the_lead_is_unassailable():
    cup = simple_cup(num_rounds=1)
    rounds = [
        ChallengeResult(
            **make_round(
                [
                    make_score("A1", [4000] * 5),
                    make_score("A2", [4000] * 5),
                    make_score("B1", [1000] * 5),
                    make_score("B2", [1000] * 5),
                ]
            )
        )
    ]

    standings = compute_standings(cup, rounds)

    assert standings.points_remaining == 0
    assert standings.is_decided
    assert standings.winner == TEAM_A_NAME


def test_players_outside_the_cup_are_ignored():
    cup = simple_cup()
    rounds = [
        ChallengeResult(
            **make_round(
                [
                    make_score("A1", [4000] * 5),
                    make_score("A2", [4000] * 5),
                    make_score("B1", [1000] * 5),
                    make_score("B2", [1000] * 5),
                    make_score("Outsider", [5000] * 5),
                ]
            )
        )
    ]

    standings = compute_standings(cup, rounds)

    assert standings.team_a_net_total == 40_000
    assert "Outsider" not in cup.team_a + cup.team_b


def test_round_entries_flag_unfinished_players():
    result = ChallengeResult(
        **make_round([make_score("A1", [4000] * 5), make_score("A2", [4000] * 3)])
    )

    entries = build_round_entries(result)

    assert entries["A1"].finished
    assert not entries["A2"].finished


# --- persistence and discovery ----------------------------------------------


def test_cup_round_trips_to_disk(tmp_path):
    cup = draw_cup(date(2025, 1, 6), 5, [f"P{i}" for i in range(8)], seed=99)

    save_cup(tmp_path, cup)
    loaded = load_cup(tmp_path, date(2025, 1, 6))

    assert loaded == cup


def test_missing_cup_returns_none(tmp_path):
    assert load_cup(tmp_path, date(2025, 1, 6)) is None


def test_active_league_takes_priority_over_finished(tmp_path):
    write_league(tmp_path, "20250106", [], active=False)
    write_league(tmp_path, "20250203", [], active=True)

    assert find_current_league_file(tmp_path).name == "league_20250203.json"


def test_falls_back_to_the_latest_finished_league(tmp_path):
    write_league(tmp_path, "20250106", [], active=False)
    write_league(tmp_path, "20250203", [], active=False)

    assert find_current_league_file(tmp_path).name == "league_20250203.json"


def test_no_league_at_all(tmp_path):
    assert find_current_league_file(tmp_path) is None
    assert load_current_standings(tmp_path) is None


def test_end_to_end_standings_from_disk(tmp_path):
    rounds = [
        make_round(
            [
                make_score("A1", [4000] * 5),
                make_score("A2", [4000] * 5),
                make_score("B1", [1000] * 5),
                make_score("B2", [1000] * 5),
            ]
        )
    ]
    write_league(tmp_path, "20250106", rounds, num_rounds=1)
    save_cup(tmp_path, simple_cup(num_rounds=1))

    standings = load_current_standings(tmp_path)

    assert standings is not None
    assert standings.team_a_points == 2


# --- formatting --------------------------------------------------------------


@pytest.mark.parametrize(
    ("points", "expected"),
    [(0, "0"), (0.5, "½"), (1, "1"), (1.5, "1½"), (3, "3"), (8.5, "8½")],
)
def test_points_are_rendered_as_halves(points, expected):
    assert format_points(points) == expected


def test_draw_message_lists_both_teams_and_the_seed():
    cup = draw_cup(date(2025, 1, 6), 5, [f"P{i}" for i in range(10)], seed=42)

    message = format_draw_html(cup)

    for player in cup.team_a + cup.team_b:
        assert player in message
    assert "42" in message
    assert message.count("<b>") == message.count("</b>")


def test_draw_message_mentions_anyone_sitting_out():
    cup = draw_cup(date(2025, 1, 6), 5, [f"P{i}" for i in range(9)], seed=7)

    assert cup.sat_out[0] in format_draw_html(cup)


def test_standings_and_scorecard_render():
    cup = simple_cup(num_rounds=1)
    rounds = [
        ChallengeResult(
            **make_round(
                [
                    make_score("A1", [4000] * 5),
                    make_score("A2", [1000] * 5),
                    make_score("B1", [1000] * 5),
                    make_score("B2", [4000] * 5),
                ]
            )
        )
    ]
    standings = compute_standings(cup, rounds)

    for message in (format_standings_html(standings), format_scorecard_html(standings)):
        assert message.count("<b>") == message.count("</b>")
        assert TEAM_A_NAME in message

    assert "A1" in format_scorecard_html(standings)


def test_scorecard_before_any_rounds():
    standings = compute_standings(simple_cup(), [])

    assert "empty" in format_scorecard_html(standings)


def test_standings_preview_the_next_day():
    cup = draw_cup(date(2025, 1, 6), 5, [f"P{i}" for i in range(8)], seed=5)

    message = format_standings_html(compute_standings(cup, []))

    assert "Day 1" in message
    assert "Fourballs" in message


def test_pairs_are_joined_with_plus_not_ampersand():
    """Several real player names contain '&', so '&' cannot separate partners."""
    cup = RyderCup(
        league_date=date(2025, 1, 6),
        num_rounds=1,
        seed=1,
        team_a=["Bosnia & GetsTheGoldSweena", "Theoland"],
        team_b=["St. Bics & Devitts", "Horanje"],
        matches=[
            Match(
                round_number=1,
                match_format=RyderFormat.FOURBALL,
                side_a=["Bosnia & GetsTheGoldSweena", "Theoland"],
                side_b=["St. Bics & Devitts", "Horanje"],
            )
        ],
    )

    message = format_standings_html(compute_standings(cup, []))

    assert "Bosnia & GetsTheGoldSweena + Theoland" in message
