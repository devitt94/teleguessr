from pathlib import Path
import pytest
from datetime import date

from teleguessr.bets import BetManager
from teleguessr.models import BetType, MarketType
from teleguessr.odds import FractionalOdds
from teleguessr.settings import ModelSettings


@pytest.fixture
def data_dir(tmp_path) -> Path:
    # Create a temporary directory for test data
    return Path(tmp_path / "test_data")


@pytest.fixture
def bet_manager(data_dir: Path) -> BetManager:
    # Create a BetManager instance with test parameters
    model_settings = ModelSettings()  # Replace with actual ModelSettings if needed
    league_date = date(2024, 1, 1)  # Replace with a specific test date
    all_runners = ["Runner1", "Runner2", "Runner3"]  # Replace with actual test runners

    return BetManager(model_settings, data_dir, league_date, all_runners)


def test_place_bet(bet_manager: BetManager):
    # Test placing a bet
    bettor = "TestBettor"
    runner = "Runner1"
    stake = 10.0
    odds = FractionalOdds(1, 1)
    market_type = MarketType.WINNER
    bet_type = BetType.BACK

    bet_manager.place_bet(bettor, runner, stake, odds, market_type, bet_type)

    # Verify that the bet was placed correctly
    bets = bet_manager.get_all_bets()

    assert len(bets) == 1  # Ensure only one bet was placed
    bet = bets[0]
    assert bet.bettor == bettor
    assert bet.runner == runner
    assert bet.stake == stake
    assert bet.odds == odds.decimal


def test_get_compute_position(bet_manager: BetManager):
    # Test computing the current position for a bettor and runner
    bettor = "TestBettor"
    market = MarketType.WINNER

    # Place a bet
    bet_manager.place_bet(
        bettor, "Runner1", 10.0, FractionalOdds(3, 1), market, BetType.BACK
    )
    bet_manager.place_bet(
        bettor, "Runner1", 10.0, FractionalOdds(1, 1), market, BetType.LAY
    )
    bet_manager.place_bet(
        bettor, "Runner2", 5.0, FractionalOdds(2, 1), market, BetType.BACK
    )

    # Compute the current position
    position = bet_manager.compute_position(bettor, market)
    assert position == {
        "Runner1": 15.0,
        "Runner2": 10.0,
        "Runner3": -5.0,
    }
