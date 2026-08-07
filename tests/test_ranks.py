import pytest
from teleguessr.ranks import get_ranks_from_scores


@pytest.mark.parametrize(
    ("scores", "expected_ranks"),
    (
        (
            {"Alice": 150, "Bob": 120, "Charlie": 150, "Dave": 100},
            {"Alice": 1, "Bob": 3, "Charlie": 1, "Dave": 4},
        ),
        (
            {"Eve": 180, "Frank": 200, "Grace": 150},
            {"Grace": 3, "Eve": 2, "Frank": 1},
        ),
        (
            {"Heidi": 90, "Ivan": 90, "Judy": 90},
            {"Heidi": 1, "Ivan": 1, "Judy": 1},
        ),
        (
            {"Mallory": 110, "Niaj": 130, "Olivia": 120, "Peggy": 140},
            {"Mallory": 4, "Niaj": 2, "Olivia": 3, "Peggy": 1},
        ),
        (
            {"Alice": 150, "Bob": 100, "Charlie": 100, "Dave": 100, "Eve": 50},
            {"Alice": 1, "Bob": 2, "Charlie": 2, "Dave": 2, "Eve": 5},
        ),
        (
            {"Alice": 100, "Bob": 100, "Charlie": 100, "Dave": 50},
            {"Alice": 1, "Bob": 1, "Charlie": 1, "Dave": 4},
        ),
    ),
)
def test_get_ranks_from_scores(scores, expected_ranks):
    ranks = get_ranks_from_scores(scores)
    assert ranks == expected_ranks
