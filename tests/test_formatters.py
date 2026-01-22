from teleguessr.formatters import get_rank_emoji, get_position_str
import pytest


@pytest.mark.parametrize(
    ("pos", "tied", "expected_str"),
    [
        (1, False, "1st"),
        (2, False, "2nd"),
        (3, False, "3rd"),
        (4, False, "4th"),
        (11, False, "11th"),
        (12, False, "12th"),
        (13, False, "13th"),
        (21, False, "21st"),
        (1, True, "=1st"),
    ],
)
def test_get_position_str(pos: int, tied: bool, expected_str: str):
    assert get_position_str(pos, tied) == expected_str


@pytest.mark.parametrize(
    ("position", "total", "expected_emoji"),
    [
        (1, 5, "🦈"),
        (2, 5, "🥈"),
        (3, 5, "🥉"),
        (5, 5, "🐡"),
        (4, 5, "🐟"),
        (10, 10, "🐡"),
        (7, 10, "🐟"),
    ],
)
def test_get_rank_emoji(position, total, expected_emoji):
    assert get_rank_emoji(position, total) == expected_emoji
