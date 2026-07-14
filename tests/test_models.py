import pytest


@pytest.mark.parametrize(
    (
        "num_rounds",
        "num_guesses",
        "gross_score",
        "handicap_multiplier",
        "expected_adjustment",
    ),
    [
        (10, 10, 35_000, 0.5, 7500),
        (10, 10, 50_000, 0.3, 0),
        (10, 10, 25_000, 0.2, 5000),
        (10, 5, 25_000, 0.2, 0),
        (10, 10, 10_000, 0.5, 12500),
        (10, 8, 39_000, 0.05, 50),
    ],
)
def test_ChallengeScore_compute_hcap_adjustment(
    num_rounds, num_guesses, gross_score, handicap_multiplier, expected_adjustment
):
    from teleguessr.models import ChallengeScore, Player, Guess

    player = Player(name="Test Player", hcap_multiplier=handicap_multiplier)
    guesses = [
        Guess(score=gross_score // num_guesses, distance_km=0.0)
        for _ in range(num_guesses)
    ]
    challenge_score = ChallengeScore(
        player=player, guesses=guesses, num_rounds=num_rounds
    )

    assert challenge_score.compute_hcap_adjustment() == expected_adjustment
