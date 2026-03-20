from teleguessr.handicaps import calculate_new_handicaps, get_adjustments
from teleguessr.settings import LeagueSettings, MAXIMUM_HANDICAP_MULTIPLIER
from unittest.mock import patch

import pytest


@pytest.fixture
def current_handicaps():
    return {
        "Alice": 0.0,
        "Bob": 0.02,
        "Charlie": round(MAXIMUM_HANDICAP_MULTIPLIER - 0.03, 2),
        "Dave": round(MAXIMUM_HANDICAP_MULTIPLIER, 2),
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
            {
                "Alice": 0.0,
                "Bob": 0.03,
                "Charlie": round(MAXIMUM_HANDICAP_MULTIPLIER, 2),
                "Dave": round(MAXIMUM_HANDICAP_MULTIPLIER, 2),
            },
        ),
        (
            {"Alice": 1, "Bob": 3, "Charlie": 3, "Dave": 4},
            {
                "Alice": 0.0,
                "Bob": 0.05,
                "Charlie": round(MAXIMUM_HANDICAP_MULTIPLIER, 2),
                "Dave": round(MAXIMUM_HANDICAP_MULTIPLIER, 2),
            },
        ),
        (
            {"Alice": 4, "Bob": 1, "Charlie": 2, "Dave": 3},
            {
                "Alice": 0.02,
                "Bob": 0.0,
                "Charlie": round(MAXIMUM_HANDICAP_MULTIPLIER - 0.04, 2),
                "Dave": round(MAXIMUM_HANDICAP_MULTIPLIER, 2),
            },
        ),
        (
            {"Alice": 2, "Bob": 3, "Charlie": 4, "Dave": 1},
            {
                "Alice": 0.0,
                "Bob": 0.04,
                "Charlie": round(MAXIMUM_HANDICAP_MULTIPLIER, 2),
                "Dave": round(MAXIMUM_HANDICAP_MULTIPLIER - 0.01, 2),
            },
        ),
        (
            {"Alice": 4, "Bob": 3, "Charlie": 2, "Dave": 1},
            {
                "Alice": 0.0,
                "Bob": 0.01,
                "Charlie": round(MAXIMUM_HANDICAP_MULTIPLIER - 0.06, 2),
                "Dave": round(MAXIMUM_HANDICAP_MULTIPLIER - 0.04, 2),
            },
        ),
        (
            {"Alice": 1, "Bob": 2, "Charlie": 3, "Dave": 4, "Eve": 5},
            {
                "Alice": 0.0,
                "Bob": 0.03,
                "Charlie": round(MAXIMUM_HANDICAP_MULTIPLIER - 0.01, 2),
                "Dave": round(MAXIMUM_HANDICAP_MULTIPLIER, 2),
                "Eve": 0.04,
            },
        ),
        (
            {"Alice": 3, "Bob": 1, "Dave": 2},
            {
                "Alice": 0.00,
                "Bob": 0.00,
                "Charlie": round(MAXIMUM_HANDICAP_MULTIPLIER - 0.03, 2),
                "Dave": round(MAXIMUM_HANDICAP_MULTIPLIER - 0.01, 2),
            },
        ),
    ],
)
def test_calculate_new_handicaps(
    current_handicaps, player_ranks, expected_new_handicaps
):
    with patch(
        "teleguessr.handicaps.get_latest_handicaps"
    ) as mock_get_latest_handicaps:
        mock_get_latest_handicaps.return_value = current_handicaps
        new_handicaps = calculate_new_handicaps(
            player_ranks, LeagueSettings(map_id="test_map")
        )

    assert new_handicaps == expected_new_handicaps
