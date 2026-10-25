from datetime import datetime, timedelta

import pytest


from teleguessr.models import (
    EFFECTIVE_HANDICAP_MULTIPLIER,
    Bet,
    BetType,
    ChallengeSettings,
    MarketType,
    ChallengeScore,
    Player,
    Guess,
    ActiveRound,
)
from freezegun import freeze_time


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
        (10, 10, 40_000, -0.05, -500),
        (10, 10, 40_000, -0.5, -5000),
        (10, 10, 20_000, -0.8, -20_000),
    ],
)
def test_ChallengeScore_compute_hcap_adjustment(
    num_rounds, num_guesses, gross_score, handicap_multiplier, expected_adjustment
):
    player = Player(name="Test Player", hcap_multiplier=handicap_multiplier)
    guesses = [
        Guess(score=gross_score // num_guesses, distance_km=0.0)
        for _ in range(num_guesses)
    ]
    challenge_score = ChallengeScore(
        player=player, guesses=guesses, num_rounds=num_rounds
    )

    assert challenge_score.compute_hcap_adjustment() == round(
        expected_adjustment * EFFECTIVE_HANDICAP_MULTIPLIER
    )


@pytest.mark.parametrize(
    ("stake", "odds", "bet_type", "expected_profit"),
    [
        (100.0, 2.0, BetType.BACK, 100.0),
        (100.0, 2.0, BetType.LAY, 100.0),
        (50.0, 3.0, BetType.BACK, 100.0),
        (50.0, 3.0, BetType.LAY, 25.0),
        (10.0, 1.5, BetType.BACK, 5.0),
        (10.0, 1.5, BetType.LAY, 20.0),
    ],
)
def test_Bet_potential_profit(stake, odds, bet_type, expected_profit):
    bet = Bet(
        bettor="Test Bettor",
        runner="Test Runner",
        stake=stake,
        odds=odds,
        market_type=MarketType.WINNER,
        bet_type=bet_type,
    )

    assert bet.potential_profit == expected_profit


@pytest.mark.parametrize(
    ("stake", "odds", "bet_type", "expected_return"),
    [
        (100.0, 2.0, BetType.BACK, 200.0),
        (100.0, 2.0, BetType.LAY, 200.0),
        (50.0, 3.0, BetType.BACK, 150.0),
        (50.0, 3.0, BetType.LAY, 75.0),
        (10.0, 1.5, BetType.BACK, 15.0),
        (10.0, 1.5, BetType.LAY, 30.0),
    ],
)
def test_Bet_potential_return(stake, odds, bet_type, expected_return):
    bet = Bet(
        bettor="Test Bettor",
        runner="Test Runner",
        stake=stake,
        odds=odds,
        market_type=MarketType.WINNER,
        bet_type=bet_type,
    )

    assert bet.potential_return == expected_return


def _make_challenge_settings() -> ChallengeSettings:
    return ChallengeSettings(
        map_id="blah",
        time_limit_seconds=10,
        move_allowed=True,
        pan_allowed=True,
        zoom_allowed=True,
    )


def test_ActiveRound_should_send_first_reminder():
    with freeze_time("2026-10-11 21:00:00") as clock:
        round = ActiveRound(
            challenge_url="blah",
            challenge_settings=_make_challenge_settings(),
            end_time=datetime.now() + timedelta(hours=24),
        )

        clock.tick(timedelta(hours=20, seconds=10))

        assert round.should_send_reminder(as_of=datetime.now())


def test_ActiveRound_should_send_subsequent_reminder():
    with freeze_time("2026-10-11 21:00:00") as clock:
        round = ActiveRound(
            challenge_url="blah",
            challenge_settings=_make_challenge_settings(),
            end_time=datetime.now() + timedelta(hours=24),
            last_reminder_sent=datetime.now() + timedelta(hours=20, minutes=2),
        )

        clock.tick(timedelta(hours=22, seconds=10))

        assert round.should_send_reminder(as_of=datetime.now())


def test_ActiveRound_should_not_send_reminder_already_sent():
    with freeze_time("2026-10-11 21:00:00") as clock:
        round = ActiveRound(
            challenge_url="blah",
            challenge_settings=_make_challenge_settings(),
            end_time=datetime.now() + timedelta(hours=24),
            last_reminder_sent=datetime.now() + timedelta(hours=20, minutes=2),
        )

        clock.tick(timedelta(hours=20, seconds=10))

        assert not round.should_send_reminder(as_of=datetime.now())
