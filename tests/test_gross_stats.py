import json

import pytest

from teleguessr.other_handlers.gross_formatters import (
    format_gross_stats_html,
    split_message,
)
from teleguessr.other_handlers.gross_stats import (
    SortKey,
    compute_gross_stats,
    finishers,
    head_to_head,
    locations_in_round,
)
from teleguessr.models import ChallengeResult


def make_score(name: str, guess_scores: list[int], hcap: float = 0.0) -> dict:
    return {
        "player": {"name": name, "hcap_multiplier": hcap},
        "guesses": [
            {"score": score, "distance_km": float(5000 - score)}
            for score in guess_scores
        ],
        "num_rounds": len(guess_scores),
    }


def make_round(scores: list[dict], locations: int = 5, url: str = "c1") -> dict:
    return {
        "challenge_url": f"https://www.geoguessr.com/challenge/{url}",
        "scores": scores,
        "challenge_settings": {
            "map_id": "world",
            "time_limit_seconds": 60,
            "pan_allowed": True,
            "zoom_allowed": True,
            "move_allowed": True,
            "number_of_locations": locations,
        },
    }


@pytest.fixture
def finished_league_dir(tmp_path):
    return tmp_path / "leagues" / "finished"


def write_league(finished_league_dir, date_str: str, rounds: list[dict]) -> None:
    finished_league_dir.mkdir(parents=True, exist_ok=True)
    league_file = finished_league_dir / f"league_{date_str}.json"
    league_file.write_text(json.dumps({"num_rounds": len(rounds), "results": rounds}))


def test_locations_in_round_falls_back_to_longest_guess_list():
    round_data = make_round([make_score("A", [1000] * 5)])
    round_data.pop("challenge_settings")
    result = ChallengeResult(**round_data)

    assert locations_in_round(result) == 5


def test_finishers_excludes_incomplete_players():
    result = ChallengeResult(
        **make_round(
            [
                make_score("A", [1000] * 5),
                make_score("B", [1000] * 3),
            ]
        )
    )

    assert [score.player.name for score in finishers(result)] == ["A"]


def test_handicaps_are_ignored(finished_league_dir):
    """A big handicap wins the net league but must not touch the gross table."""
    write_league(
        finished_league_dir,
        "20250101",
        [
            make_round(
                [
                    make_score("Strong", [4000] * 5, hcap=0.0),
                    make_score("Handicapped", [2000] * 5, hcap=0.9),
                    make_score("Middling", [3000] * 5, hcap=0.0),
                ]
            )
        ],
    )

    table = compute_gross_stats(finished_league_dir)
    by_name = {stats.player: stats for stats in table.players}

    assert by_name["Strong"].avg_points_per_location == 4000
    assert by_name["Strong"].avg_position == 1
    assert by_name["Handicapped"].avg_position == 3
    assert by_name["Handicapped"].total_gross_points == 10_000


def test_rounds_below_min_finishers_are_skipped(finished_league_dir):
    write_league(
        finished_league_dir,
        "20250101",
        [make_round([make_score("A", [1000] * 5), make_score("B", [2000] * 5)])],
    )

    table = compute_gross_stats(finished_league_dir)

    assert table.rounds_counted == 0
    assert table.players == []


def test_incomplete_rounds_do_not_count_towards_a_players_average(finished_league_dir):
    """A player who abandons a round should be untouched by it, not penalised."""
    write_league(
        finished_league_dir,
        "20250101",
        [
            make_round(
                [
                    make_score("A", [4000] * 5),
                    make_score("B", [3000] * 5),
                    make_score("C", [2000] * 5),
                ],
                url="r1",
            ),
            make_round(
                [
                    make_score("A", [4000] * 5),
                    make_score("B", [3000] * 5),
                    make_score("C", [2000] * 5),
                    make_score("Quitter", [10] * 2),
                ],
                url="r2",
            ),
        ],
    )

    table = compute_gross_stats(finished_league_dir)
    by_name = {stats.player: stats for stats in table.players}

    assert "Quitter" not in by_name
    assert by_name["A"].rounds_played == 2
    assert by_name["A"].avg_points_per_location == 4000


def test_positions_use_competition_ranking_for_ties(finished_league_dir):
    write_league(
        finished_league_dir,
        "20250101",
        [
            make_round(
                [
                    make_score("A", [4000] * 5),
                    make_score("B", [4000] * 5),
                    make_score("C", [2000] * 5),
                ]
            )
        ],
    )

    by_name = {
        stats.player: stats
        for stats in compute_gross_stats(finished_league_dir).players
    }

    assert by_name["A"].avg_position == 1
    assert by_name["B"].avg_position == 1
    assert by_name["C"].avg_position == 3
    assert by_name["A"].round_wins == 1
    assert by_name["B"].round_wins == 1


def test_rounds_of_different_lengths_are_normalised(finished_league_dir):
    """5- and 10-location rounds must be comparable per location, not per round."""
    write_league(
        finished_league_dir,
        "20250101",
        [
            make_round(
                [
                    make_score("A", [3000] * 5),
                    make_score("B", [2000] * 5),
                    make_score("C", [1000] * 5),
                ],
                locations=5,
                url="r1",
            ),
            make_round(
                [
                    make_score("A", [3000] * 10),
                    make_score("B", [2000] * 10),
                    make_score("C", [1000] * 10),
                ],
                locations=10,
                url="r2",
            ),
        ],
    )

    by_name = {
        stats.player: stats
        for stats in compute_gross_stats(finished_league_dir).players
    }

    assert by_name["A"].avg_points_per_location == 3000
    assert by_name["A"].locations_played == 15
    assert by_name["A"].total_gross_points == 45_000
    assert by_name["A"].avg_points_per_round == 22_500


def test_stats_aggregate_across_leagues(finished_league_dir):
    round_data = [
        make_score("A", [4000] * 5),
        make_score("B", [3000] * 5),
        make_score("C", [2000] * 5),
    ]
    write_league(finished_league_dir, "20250101", [make_round(round_data)])
    write_league(finished_league_dir, "20250201", [make_round(round_data)])

    table = compute_gross_stats(finished_league_dir)

    assert table.leagues_counted == 2
    assert table.rounds_counted == 2
    assert table.first_round_date.isoformat() == "2025-01-01"
    assert table.last_round_date.isoformat() == "2025-02-01"


def test_renamed_players_are_merged(finished_league_dir):
    write_league(
        finished_league_dir,
        "20250101",
        [
            make_round(
                [
                    make_score("Boothd", [4000] * 5),
                    make_score("B", [3000] * 5),
                    make_score("C", [2000] * 5),
                ],
                url="r1",
            ),
            make_round(
                [
                    make_score("Boothlandia", [4000] * 5),
                    make_score("B", [3000] * 5),
                    make_score("C", [2000] * 5),
                ],
                url="r2",
            ),
        ],
    )

    by_name = {
        stats.player: stats
        for stats in compute_gross_stats(finished_league_dir).players
    }

    assert "Boothd" not in by_name
    assert by_name["Boothlandia"].rounds_played == 2


@pytest.mark.parametrize(
    ("sort_key", "expected_first"),
    [
        (SortKey.POINTS_PER_LOCATION, "Consistent"),
        (SortKey.AVERAGE_POSITION, "Consistent"),
        (SortKey.TOTAL_POINTS, "Prolific"),
        (SortKey.ROUND_WINS, "Prolific"),
    ],
)
def test_sorting(finished_league_dir, sort_key, expected_first):
    """Consistent is better per location; Prolific accumulates more by playing more."""
    write_league(
        finished_league_dir,
        "20250101",
        [
            make_round(
                [
                    make_score("Consistent", [4500] * 5),
                    make_score("Prolific", [4000] * 5),
                    make_score("Filler", [1000] * 5),
                ],
                url="r1",
            ),
            make_round(
                [
                    make_score("Prolific", [4000] * 5),
                    make_score("Filler", [1000] * 5),
                    make_score("Filler2", [900] * 5),
                ],
                url="r2",
            ),
            make_round(
                [
                    make_score("Prolific", [4000] * 5),
                    make_score("Filler", [1000] * 5),
                    make_score("Filler2", [900] * 5),
                ],
                url="r3",
            ),
        ],
    )

    table = compute_gross_stats(finished_league_dir)

    assert table.sorted_by(sort_key)[0].player == expected_first


@pytest.mark.parametrize(
    ("arg", "expected"),
    [
        (None, SortKey.POINTS_PER_LOCATION),
        ("pos", SortKey.AVERAGE_POSITION),
        ("TOTAL", SortKey.TOTAL_POINTS),
        (" wins ", SortKey.ROUND_WINS),
        ("nonsense", SortKey.POINTS_PER_LOCATION),
    ],
)
def test_sort_key_parse(arg, expected):
    assert SortKey.parse(arg) == expected


def test_head_to_head_only_counts_shared_rounds(finished_league_dir):
    write_league(
        finished_league_dir,
        "20250101",
        [
            make_round(
                [
                    make_score("A", [4000] * 5),
                    make_score("B", [3000] * 5),
                    make_score("C", [2000] * 5),
                ],
                url="r1",
            ),
            make_round(
                [
                    make_score("A", [1000] * 5),
                    make_score("C", [2000] * 5),
                    make_score("D", [2000] * 5),
                ],
                url="r2",
            ),
        ],
    )

    assert head_to_head(finished_league_dir, "A", "B") == {"A": 1}


def test_empty_data_dir_produces_empty_table(tmp_path):
    table = compute_gross_stats(tmp_path)

    assert table.players == []
    assert table.rounds_counted == 0
    assert "No completed rounds" in format_gross_stats_html(table)


def test_formatted_message_contains_every_player(finished_league_dir):
    write_league(
        finished_league_dir,
        "20250101",
        [
            make_round(
                [
                    make_score("A", [4000] * 5),
                    make_score("B", [3000] * 5),
                    make_score("C", [2000] * 5),
                ]
            )
        ],
    )

    message = format_gross_stats_html(compute_gross_stats(finished_league_dir))

    for name in ("A", "B", "C"):
        assert name in message
    assert message.count("<b>") == message.count("</b>")


def test_split_message_respects_limit_and_preserves_lines():
    text = "\n".join(f"line {i}" for i in range(500))

    chunks = split_message(text, limit=200)

    assert all(len(chunk) <= 200 for chunk in chunks)
    assert "\n".join(chunks) == text
