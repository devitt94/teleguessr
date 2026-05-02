from datetime import date
from pathlib import Path

from teleguessr.settings import ModelSettings

from loguru import logger
import json

BET_AMOUNTS = [
    0.1,
    0.2,
    0.3,
    0.5,
    1,
    2,
    3,
    5,
    7,
    10,
    15,
    20,
    25,
    30,
    35,
    40,
    45,
    50,
    60,
    70,
    80,
    90,
    100,
    120,
    140,
    160,
    180,
    200,
    250,
    300,
    350,
    400,
    450,
    500,
]


class BetManager:
    def __init__(
        self, model_settings: ModelSettings, data_dir: Path, league_date: date
    ):
        self.model_settings = model_settings
        self.odds_dir = data_dir / "odds"
        self.bets_dir = data_dir / "bets"
        self.league_date = league_date
        self.odds_dir.mkdir(parents=True, exist_ok=True)
        self.bets_dir.mkdir(parents=True, exist_ok=True)

    def get_latest_odds(self, league_round: int) -> dict[str, float]:
        odds_file = (
            self.odds_dir
            / f"league_{self.league_date.strftime('%Y%m%d')}_round_{league_round}.json"
        )
        if not odds_file.exists():
            logger.warning(f"{odds_file} does not exist. Returning empty odds.")
            return {}

        with open(odds_file, "r") as f:
            odds_data = json.load(f)

        return odds_data

    def get_current_position(self, bettor: str, runner: str) -> float:
        bets_file = self.bets_dir / f"bets_{self.league_date.strftime('%Y%m%d')}.json"
        if not bets_file.exists():
            return 0.0
        with open(bets_file, "r") as f:
            bets_data = json.load(f)
        position = 0.0
        for bet in bets_data:
            if bet["bettor"] != bettor:
                continue
            if bet["runner"] == runner:
                position += bet["amount"] * (bet["odds"] - 1)
            else:
                position -= bet["amount"]

        return position

    def calculate_bet_amounts(
        self,
        bettor: str,
        runner: str,
        odds: float,
    ) -> list[float]:
        """Calculate bet amounts based on odds and settings."""
        bet_on_self = bettor == runner
        min_stake = self.model_settings.min_profit_bet / (odds - 1)
        max_profit = (
            self.model_settings.max_profit_self_bet
            if bet_on_self
            else self.model_settings.max_profit_non_self_bet
        )

        current_position = self.get_current_position(bettor, runner)
        logger.info(
            f"Current position for bettor {bettor} on runner {runner}: {current_position:.2f}"
        )
        adjusted_max_profit = max_profit - current_position
        max_stake = round(adjusted_max_profit / (odds - 1), 2)
        logger.info(
            f"Adjusted max profit for bettor {bettor} on runner {runner}: {adjusted_max_profit:.2f}"
        )
        logger.info(
            f"Max stake for bettor {bettor} on runner {runner}: {max_stake:.2f}"
        )

        # Filter bet amounts to be within min and max stake
        valid_bets = [
            round(amount, 2)
            for amount in BET_AMOUNTS
            if min_stake <= amount <= max_stake
        ]
        if valid_bets and valid_bets[-1] != max_stake:
            valid_bets.append(max_stake)

        return valid_bets

    def update_odds(self, round_num: int, odds: dict[str, float]) -> None:
        odds_file = (
            self.odds_dir
            / f"league_{self.league_date.strftime('%Y%m%d')}_round_{round_num}.json"
        )
        with odds_file.open("w") as f:
            json.dump(odds, f, indent=2)

    def place_bet(self, bettor: str, runner: str, amount: float, odds: float) -> None:
        bet_data = {
            "bettor": bettor,
            "runner": runner,
            "amount": amount,
            "odds": odds,
            "return": amount * odds,
        }
        bet_file = self.bets_dir / f"bets_{self.league_date.strftime('%Y%m%d')}.json"
        if bet_file.exists():
            with bet_file.open("r") as f:
                existing_bets = json.load(f)
        else:
            existing_bets = []

        existing_bets.append(bet_data)
        with bet_file.open("w") as f:
            json.dump(existing_bets, f, indent=2)
