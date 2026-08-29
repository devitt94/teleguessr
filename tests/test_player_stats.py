import json

import pytest

from teleguessr.models import ChallengeSettings
from teleguessr.other_handlers.player_formatters import format_player_profile_html
from teleguessr.other_handlers.player_handler import (
    decode_callback_data,
    encode_callback_data,
    MAX_CALLBACK_DATA_BYTES,
)
from teleguessr.other_handlers.player_stats import (
    compute_player_profile,
    list_players,
    resolve_player,
    round_type_label,
)


def make_score(name: str, guess_scores: list[int], hcap: float = 0.0) -> dict:
    return {
        "player": {"name": name, "hcap_multiplier": hcap},
        "guesses": [
            {"score": score, "distance_km": float(5000 - score)}
            for score in guess_scores
        ],
        "num_rounds": len(guess_scores),
    }


def make_round(scores: list[dict], locations: int = 5, url: str = "c1", **settings):
    challenge_settings = {
        "map_id": "WORLD",
        "time_limit_seconds": 90,
        "pan_allowed": True,
        "zoom_allowed": True,
        "move_allowed": True,
        "number_of_locations": locations,
    }
    challenge_settings.update(settings)
    return {
        "challenge_url": f"https://www.geoguessr.com/challenge/{url}",
        "scores": scores,
        "challenge_settings": challenge_settings,
    }


def write_league(data_dir, date_str, rounds, scores=None):
    finished = data_dir / "leagues" / "finished"
    finished.mkdir(parents=True, exist_ok=True)
    (finished / f"league_{date_str}.json").write_text(
        json.dumps(
            {"num_rounds": len(rounds), "results": rounds, "scores": scores or {}}
        )
    )


def write_bets(data_dir, date_str, bets):
    bets_dir = data_dir / "bets"
    bets_dir.mkdir(parents=True, exist_ok=True)
    (bets_dir / f"bets_{date_str}.json").write_text(json.dumps(bets))


def standard_round(url="r1", **kwargs):
    return make_round(
        [
            make_score("Alice", [4000] * 5),
            make_score("Bob", [3000] * 5),
            make_score("Carol", [2000] * 5),
        ],
        url=url,
        **kwargs,
    )


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path


def test_round_type_label_describes_the_rules():
    nmpz = ChallengeSettings(
        map_id="WORLD",
        time_limit_seconds=15,
        pan_allowed=False,
        zoom_allowed=False,
        move_allowed=False,
    )
    assert round_type_label(nmpz) == "Classic World · 15s · NMPZ"

    moving = ChallengeSettings(
        map_id="640d01bf1b14982128374759",
        time_limit_seconds=90,
        pan_allowed=True,
        zoom_allowed=True,
        move_allowed=True,
    )
    assert round_type_label(moving) == "Urban World · 90s · Moving"

    assert round_type_label(None) == "Unknown"


def test_list_and_resolve_players(data_dir):
    write_league(data_dir, "20250106", [standard_round()])

    assert list_players(data_dir) == ["Alice", "Bob", "Carol"]
    assert resolve_player(data_dir, "ali") == ["Alice"]
    assert resolve_player(data_dir, "ALICE") == ["Alice"]
    assert resolve_player(data_dir, "a") == ["Alice", "Carol"]
    assert resolve_player(data_dir, "nobody") == []
    assert resolve_player(data_dir, "") == ["Alice", "Bob", "Carol"]


def test_unknown_player_has_no_profile(data_dir):
    write_league(data_dir, "20250106", [standard_round()])

    assert compute_player_profile(data_dir, "Nobody") is None


def test_core_scoring_and_positions(data_dir):
    write_league(
        data_dir,
        "20250106",
        [standard_round("r1"), standard_round("r2")],
        scores={"Alice": 28, "Bob": 22, "Carol": 18},
    )

    profile = compute_player_profile(data_dir, "Alice")

    assert profile.rounds_played == 2
    assert profile.leagues_played == 1
    assert profile.avg_points_per_location == 4000
    assert profile.avg_points_per_round == 20_000
    assert profile.total_gross_points == 40_000
    assert profile.avg_gross_position == 1
    assert profile.gross_round_wins == 2
    assert profile.gross_podiums == 2


def test_league_honours_use_saved_final_scores(data_dir):
    write_league(
        data_dir,
        "20250106",
        [standard_round()],
        scores={"Alice": 30, "Bob": 20, "Carol": 10},
    )
    write_league(
        data_dir,
        "20250203",
        [standard_round()],
        scores={"Bob": 30, "Alice": 20, "Carol": 10},
    )

    alice = compute_player_profile(data_dir, "Alice")
    carol = compute_player_profile(data_dir, "Carol")

    assert alice.league_wins == 1
    assert alice.league_podiums == 2
    assert alice.wooden_spoons == 0
    assert alice.avg_league_finish == 1.5
    assert carol.wooden_spoons == 2


def test_weekday_split_uses_league_start_plus_round_index(data_dir):
    # 6 Jan 2025 is a Monday, so round two lands on the Tuesday.
    write_league(data_dir, "20250106", [standard_round("r1"), standard_round("r2")])

    profile = compute_player_profile(data_dir, "Alice")
    labels = [split.label for split in profile.by_weekday]

    assert labels == ["Monday", "Tuesday"]


def test_round_type_split_separates_formats(data_dir):
    write_league(
        data_dir,
        "20250106",
        [
            make_round(
                [
                    make_score("Alice", [4500] * 5),
                    make_score("Bob", [3000] * 5),
                    make_score("Carol", [2000] * 5),
                ],
                url="r1",
                move_allowed=True,
            ),
            make_round(
                [
                    make_score("Alice", [1000] * 5),
                    make_score("Bob", [3000] * 5),
                    make_score("Carol", [2000] * 5),
                ],
                url="r2",
                move_allowed=False,
                pan_allowed=False,
                time_limit_seconds=15,
            ),
        ],
    )

    profile = compute_player_profile(data_dir, "Alice")
    by_label = {split.label: split for split in profile.by_round_type}

    assert by_label["Classic World · 90s · Moving"].avg_points_per_location == 4500
    assert by_label["Classic World · 15s · NMPZ"].avg_points_per_location == 1000


def test_guess_quality_counts(data_dir):
    write_league(
        data_dir,
        "20250106",
        [
            make_round(
                [
                    make_score("Alice", [5000, 5000, 999, 0, 3000]),
                    make_score("Bob", [3000] * 5),
                    make_score("Carol", [2000] * 5),
                ]
            )
        ],
    )

    profile = compute_player_profile(data_dir, "Alice")

    assert profile.total_guesses == 5
    assert profile.perfect_guesses == 2
    assert profile.dud_guesses == 2  # 999 and 0
    assert profile.zero_guesses == 1
    assert profile.perfect_guess_rate == pytest.approx(0.4)


def test_head_to_head_records(data_dir):
    write_league(
        data_dir,
        "20250106",
        [standard_round(f"r{i}") for i in range(6)],
    )

    profile = compute_player_profile(data_dir, "Bob")

    assert profile.bunny.opponent == "Carol"
    assert profile.bunny.wins == 6
    assert profile.nemesis.opponent == "Alice"
    assert profile.nemesis.losses == 6


def test_head_to_head_needs_enough_meetings(data_dir):
    write_league(data_dir, "20250106", [standard_round()])

    profile = compute_player_profile(data_dir, "Bob")

    assert profile.bunny is None
    assert profile.nemesis is None


def test_recent_form_is_chronological_and_capped(data_dir):
    write_league(data_dir, "20250106", [standard_round(f"r{i}") for i in range(12)])

    profile = compute_player_profile(data_dir, "Alice")

    assert len(profile.recent_form) == 8
    assert profile.recent_form == [1] * 8


def test_handicap_history(data_dir):
    write_league(data_dir, "20250106", [standard_round()])
    handicaps = data_dir / "handicaps"
    handicaps.mkdir()
    (handicaps / "handicaps_league_20250106.json").write_text(
        json.dumps({"Alice": 0.1})
    )
    (handicaps / "handicaps_league_20250203.json").write_text(
        json.dumps({"Alice": 0.3})
    )
    (handicaps / "handicaps_league_20250303.json").write_text(
        json.dumps({"Alice": 0.2})
    )

    profile = compute_player_profile(data_dir, "Alice")

    assert profile.current_handicap == 0.2
    assert profile.min_handicap == 0.1
    assert profile.max_handicap == 0.3


def test_betting_pnl_settles_against_the_net_league_winner(data_dir):
    write_league(
        data_dir,
        "20250106",
        [standard_round()],
        scores={"Alice": 30, "Bob": 20, "Carol": 10},
    )
    write_bets(
        data_dir,
        "20250106",
        [
            # Winning back: +10 profit at 2.0 on the eventual winner.
            {
                "bettor": "Bob",
                "runner": "Alice",
                "stake": 10.0,
                "odds": 2.0,
                "market_type": "WINNER",
                "bet_type": "BACK",
            },
            # Losing back: -5.
            {
                "bettor": "Bob",
                "runner": "Carol",
                "stake": 5.0,
                "odds": 3.0,
                "market_type": "WINNER",
                "bet_type": "BACK",
            },
            # Someone else's bet must not leak in.
            {
                "bettor": "Carol",
                "runner": "Alice",
                "stake": 100.0,
                "odds": 2.0,
                "market_type": "WINNER",
                "bet_type": "BACK",
            },
        ],
    )

    betting = compute_player_profile(data_dir, "Bob").betting

    assert betting.bets_placed == 2
    assert betting.total_staked == 15.0
    assert betting.profit_and_loss == pytest.approx(5.0)
    assert betting.biggest_win == pytest.approx(10.0)
    assert betting.biggest_loss == pytest.approx(-5.0)
    assert betting.leagues_bet_in == 1
    assert betting.most_backed_runner == "Alice"


def test_betting_tracks_backing_yourself(data_dir):
    write_league(
        data_dir,
        "20250106",
        [standard_round()],
        scores={"Alice": 30, "Bob": 20, "Carol": 10},
    )
    write_bets(
        data_dir,
        "20250106",
        [
            {
                "bettor": "Bob",
                "runner": "Bob",
                "stake": 20.0,
                "odds": 4.0,
                "market_type": "WINNER",
                "bet_type": "BACK",
            },
        ],
    )

    betting = compute_player_profile(data_dir, "Bob").betting

    assert betting.bets_on_self == 1
    assert betting.pnl_backing_self == pytest.approx(-20.0)


def test_lay_bet_wins_when_the_runner_loses(data_dir):
    write_league(
        data_dir,
        "20250106",
        [standard_round()],
        scores={"Alice": 30, "Bob": 20, "Carol": 10},
    )
    write_bets(
        data_dir,
        "20250106",
        [
            {
                "bettor": "Bob",
                "runner": "Carol",
                "stake": 10.0,
                "odds": 3.0,
                "market_type": "WINNER",
                "bet_type": "LAY",
            },
        ],
    )

    betting = compute_player_profile(data_dir, "Bob").betting

    assert betting.profit_and_loss > 0


def test_no_bets_on_record(data_dir):
    write_league(data_dir, "20250106", [standard_round()])

    betting = compute_player_profile(data_dir, "Alice").betting

    assert betting.bets_placed == 0
    assert betting.profit_and_loss == 0.0


def test_profile_renders_without_optional_sections(data_dir):
    """A brand new player has no rivalries, handicaps or bets -- must not crash."""
    write_league(data_dir, "20250106", [standard_round()])

    message = format_player_profile_html(compute_player_profile(data_dir, "Alice"))

    assert "Alice" in message
    assert "No bets on record" in message
    assert message.count("<b>") == message.count("</b>")


def test_profile_renders_full_message(data_dir):
    # Alice always beats Carol but loses to Bob in four of six, so she has a
    # distinct bunny and nemesis and the rivalries section has something to say.
    rounds = [
        make_round(
            [
                make_score("Alice", [3000] * 5),
                make_score("Bob", [4000 if i < 4 else 2000] * 5),
                make_score("Carol", [1000] * 5),
            ],
            url=f"r{i}",
        )
        for i in range(6)
    ]
    write_league(
        data_dir,
        "20250106",
        rounds,
        scores={"Alice": 30, "Bob": 20, "Carol": 10},
    )
    write_bets(
        data_dir,
        "20250106",
        [
            {
                "bettor": "Alice",
                "runner": "Alice",
                "stake": 10.0,
                "odds": 2.0,
                "market_type": "WINNER",
                "bet_type": "BACK",
            },
        ],
    )

    message = format_player_profile_html(compute_player_profile(data_dir, "Alice"))

    for heading in (
        "Scoring",
        "Finishing positions",
        "League honours",
        "Guess quality",
        "Rivalries",
        "Betting",
        "Recent form",
    ):
        assert heading in message
    assert message.count("<b>") == message.count("</b>")


@pytest.mark.parametrize(
    "player",
    ["Alice", "Ppl's Rep. Glorious Mickistan", "Bosnia & GetsTheGoldSweena"],
)
def test_callback_data_round_trips(player):
    data = encode_callback_data(player)

    assert len(data.encode("utf-8")) <= MAX_CALLBACK_DATA_BYTES
    assert decode_callback_data(data, [player, "Someone Else"]) == player


def test_callback_data_for_unknown_player_returns_none():
    data = encode_callback_data("Ghost")

    assert decode_callback_data(data, ["Alice", "Bob"]) is None


def test_callback_data_truncates_absurdly_long_names():
    player = "X" * 200
    data = encode_callback_data(player)

    assert len(data.encode("utf-8")) <= MAX_CALLBACK_DATA_BYTES
    assert decode_callback_data(data, [player]) == player


def test_net_positions_account_for_handicaps(data_dir):
    """A big handicap should lift net position above gross position."""
    write_league(
        data_dir,
        "20250106",
        [
            make_round(
                [
                    make_score("Alice", [4000] * 5, hcap=0.0),
                    make_score("Bob", [3000] * 5, hcap=0.9),
                    make_score("Carol", [2000] * 5, hcap=0.0),
                ]
            )
        ],
    )

    bob = compute_player_profile(data_dir, "Bob")

    assert bob.avg_gross_position == 2
    assert bob.avg_net_position == 1
    assert bob.net_round_wins == 1
    assert bob.gross_round_wins == 0


def test_renamed_player_keeps_net_positions(data_dir):
    """Legacy names must not drop out of the net ranking."""
    write_league(
        data_dir,
        "20250106",
        [
            make_round(
                [
                    make_score("Boothd", [4000] * 5),
                    make_score("Bob", [3000] * 5),
                    make_score("Carol", [2000] * 5),
                ]
            )
        ],
    )

    profile = compute_player_profile(data_dir, "Boothlandia")

    assert profile.rounds_played == 1
    assert profile.avg_net_position == 1
    assert profile.avg_gross_position == 1
