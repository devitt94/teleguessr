from handicaps import calculate_new_handicaps, get_adjustments
from settings import LeagueSettings
from unittest.mock import patch

import pytest


@pytest.fixture
def current_handicaps():
    return {
        "Alice": 0.0,
        "Bob": 0.02,
        "Charlie": 0.27,
        "Dave": 0.30,
    }


@pytest.mark.parametrize(
    "num_players, expected_adjustments",
    [
        (5, [-0.02, -0.01, 0.0, 0.01, 0.02]),
        (4, [-0.02, -0.01, 0.01, 0.02]),
        (3, [-0.01, 0.0, 0.01]),
        (2, [-0.01, 0.01]),
    ],
)
def test_get_adjustments(num_players, expected_adjustments):
    adjustments = get_adjustments(num_players)
    assert adjustments == expected_adjustments


@pytest.mark.parametrize(
    ("player_ranks", "expected_new_handicaps"),
    [
        (
            {"Alice": 1, "Bob": 2, "Charlie": 3, "Dave": 4},
            {"Alice": 0.0, "Bob": 0.03, "Charlie": 0.30, "Dave": 0.30},
        ),
        (
            {"Alice": 1, "Bob": 3, "Charlie": 3, "Dave": 4},
            {"Alice": 0.0, "Bob": 0.05, "Charlie": 0.30, "Dave": 0.30},
        ),
        (
            {"Alice": 4, "Bob": 1, "Charlie": 2, "Dave": 3},
            {"Alice": 0.02, "Bob": 0.0, "Charlie": 0.26, "Dave": 0.30},
        ),
        (
            {"Alice": 2, "Bob": 3, "Charlie": 4, "Dave": 1},
            {"Alice": 0.0, "Bob": 0.04, "Charlie": 0.30, "Dave": 0.29},
        ),
        (
            {"Alice": 4, "Bob": 3, "Charlie": 2, "Dave": 1},
            {"Alice": 0.0, "Bob": 0.01, "Charlie": 0.24, "Dave": 0.26},
        ),
        (
            {"Alice": 1, "Bob": 2, "Charlie": 3, "Dave": 4, "Eve": 5},
            {"Alice": 0.0, "Bob": 0.03, "Charlie": 0.29, "Dave": 0.30, "Eve": 0.29},
        ),
        (
            {"Alice": 3, "Bob": 1, "Dave": 2},
            {"Alice": 0.00, "Bob": 0.00, "Charlie": 0.27, "Dave": 0.29},
        ),
    ],
)
def test_calculate_new_handicaps(
    current_handicaps, player_ranks, expected_new_handicaps
):
    with patch("handicaps.get_latest_handicaps") as mock_get_latest_handicaps:
        mock_get_latest_handicaps.return_value = current_handicaps
        new_handicaps = calculate_new_handicaps(
            player_ranks, LeagueSettings(map_id="test_map")
        )

    assert new_handicaps == expected_new_handicaps
