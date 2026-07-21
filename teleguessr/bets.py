from collections import defaultdict
from datetime import date
from pathlib import Path

from teleguessr.models import Bet, BetType, MarketType
from teleguessr.odds import FractionalOdds
from teleguessr.settings import ModelSettings

from loguru import logger
import json

BET_AMOUNTS = [
    0.01,
    0.02,
    0.03,
    0.05,
    0.1,
    0.2,
    0.3,
    0.5,
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    10,
    12,
    14,
    16,
    18,
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
    1000,
]


class BetManager:
    def __init__(
        self,
        model_settings: ModelSettings,
        data_dir: Path,
        league_date: date,
        all_runners: list[str],
    ):
        self.model_settings = model_settings
        self.odds_dir = data_dir / "odds"
        self.bets_dir = data_dir / "bets"
        self.league_date = league_date
        self.odds_dir.mkdir(parents=True, exist_ok=True)
        self.bets_dir.mkdir(parents=True, exist_ok=True)
        self.all_runners = all_runners

    def get_odds_file_path(
        self, round_num: int, market_type: MarketType, bet_type: BetType
    ) -> Path:
        return (
            self.odds_dir
            / f"league_{self.league_date.strftime('%Y%m%d')}_round_{round_num}_{bet_type.value}_{market_type.value}_odds.json"
        )

    def get_latest_odds(
        self,
        league_round: int,
        market_type: MarketType = MarketType.WINNER,
        bet_type: BetType = BetType.BACK,
    ) -> dict[str, FractionalOdds]:
        odds_file = self.get_odds_file_path(league_round, market_type, bet_type)
        if not odds_file.exists():
            logger.warning(f"{odds_file} does not exist. Returning empty odds.")
            return {}

        with open(odds_file, "r") as f:
            odds_data = json.load(f)

        return {
            runner: FractionalOdds.from_str(odds) for runner, odds in odds_data.items()
        }

    def get_all_bets(self) -> list[Bet]:
        bets_file = self.bets_dir / f"bets_{self.league_date.strftime('%Y%m%d')}.json"
        if not bets_file.exists():
            return []
        with open(bets_file, "r") as f:
            bets_data = json.load(f)
        return [Bet(**bet) for bet in bets_data]

    def get_current_position(
        self, bettor: str, runner: str, market_type: MarketType = MarketType.WINNER
    ) -> float:
        bets = self.get_all_bets()
        position = 0.0
        relevant_bets = [
            bet
            for bet in bets
            if bet.bettor == bettor and bet.market_type == market_type
        ]
        for bet in relevant_bets:
            if (bet.runner == runner) ^ (bet.bet_type == BetType.BACK):
                position -= bet.stake
            else:
                position += bet.potential_profit

        return position

    def calculate_bet_amounts(
        self,
        bettor: str,
        runner: str,
        odds: FractionalOdds,
        bet_type: BetType = BetType.BACK,
        market_type: MarketType = MarketType.WINNER,
    ) -> list[float]:
        """Calculate bet amounts based on odds and settings."""
        bet_on_self = bettor == runner
        if (
            bet_type == BetType.LAY
            and market_type != MarketType.WOODEN_SPOON
            and bet_on_self
        ):
            return []

        logger.info(
            f"Calculating bet amounts {bettor=} {runner=} {odds.formatted=} {bet_type=} {market_type=} {bet_on_self=}"
        )
        min_stake = self.model_settings.min_profit_bet / (odds.decimal - 1)
        max_stake = self.compute_max_stake(bettor, runner, odds, bet_type)
        logger.info(f"Calculated min_stake={min_stake:.2f}, max_stake={max_stake:.2f}")
        # Filter bet amounts to be within min and max stake
        valid_bets = [
            round(amount, 2)
            for amount in BET_AMOUNTS
            if min_stake <= amount <= max_stake
        ]
        if valid_bets and valid_bets[-1] != max_stake:
            valid_bets.append(max_stake)

        return valid_bets

    def update_odds(
        self,
        round_num: int,
        back_odds: dict[str, FractionalOdds],
        lay_odds: dict[str, FractionalOdds],
        market_type: MarketType = MarketType.WINNER,
    ) -> None:
        back_win_odds_file = self.get_odds_file_path(
            round_num, market_type, BetType.BACK
        )
        lay_win_odds_file = self.get_odds_file_path(round_num, market_type, BetType.LAY)
        available_odds = {
            runner: odds.formatted
            for runner, odds in back_odds.items()
            if odds is not None
        }
        with back_win_odds_file.open("w") as f:
            json.dump(available_odds, f, indent=2)

        available_odds = {
            runner: odds.formatted
            for runner, odds in lay_odds.items()
            if odds is not None
        }
        with lay_win_odds_file.open("w") as f:
            json.dump(available_odds, f, indent=2)

    def place_bet(
        self,
        bettor: str,
        runner: str,
        amount: float,
        odds: FractionalOdds,
        market_type: MarketType = MarketType.WINNER,
        bet_type: BetType = BetType.BACK,
    ) -> Bet:
        bet = Bet(
            bettor=bettor,
            runner=runner,
            stake=amount,
            odds=odds.decimal,
            market_type=market_type,
            bet_type=bet_type,
        )
        bet_file = self.bets_dir / f"bets_{self.league_date.strftime('%Y%m%d')}.json"
        if bet_file.exists():
            with bet_file.open("r") as f:
                existing_bets = json.load(f)
        else:
            existing_bets = []

        existing_bets.append(bet.model_dump())
        with bet_file.open("w") as f:
            json.dump(existing_bets, f, indent=2)

        return bet

    def compute_bet_pnls(self, winner: str) -> dict[str, float]:
        bets = self.get_all_bets()

        pnls = defaultdict(float)
        for bet in bets:
            bettor = bet.bettor
            if (bet.runner == winner) ^ (bet.bet_type == BetType.LAY):
                pnls[bettor] += bet.potential_profit
            else:
                pnls[bettor] -= bet.stake

        return dict(pnls)

    def compute_bookmaker_exposure(self) -> dict[str, float]:
        bets = self.get_all_bets()
        exposure = {runner: 0.0 for runner in self.all_runners}
        for bet in bets:
            for runner in self.all_runners:
                if bet.runner == runner:
                    if bet.bet_type == BetType.BACK:
                        exposure[runner] -= bet.potential_profit
                    else:
                        exposure[runner] += bet.stake
                else:
                    if bet.bet_type == BetType.BACK:
                        exposure[runner] += bet.stake
                    else:
                        exposure[runner] -= bet.potential_profit
        return dict(exposure)

    def compute_position(
        self, bettor: str, market_type: MarketType = MarketType.WINNER
    ) -> dict[str, float]:
        position = {}
        for runner in self.all_runners:
            position[runner] = self.get_current_position(bettor, runner, market_type)
        return position

    def compute_equity(
        self, runner: str, net_position: float, odds: FractionalOdds | None
    ) -> float:
        min_prob, max_prob = 0.00001, 0.99999
        if odds is None:
            adjusted_probability = min_prob
        else:
            adjusted_probability = (
                odds.implied_probability - 0.02
                if net_position > 0
                else odds.implied_probability + 0.02
            )
            adjusted_probability = max(min_prob, min(max_prob, adjusted_probability))
        return net_position * adjusted_probability

    @staticmethod
    def compute_signed_amount(amount: float) -> str:
        if amount > 0:
            return f"+€{amount:.2f}"
        elif amount < 0:
            return f"-€{abs(amount):.2f}"
        else:
            return "€0.00"

    def compute_max_stake(
        self,
        bettor: str,
        selected_runner: str,
        odds: FractionalOdds,
        bet_type: BetType,
    ) -> float:
        """
        Compute the maximum stake `bettor` can place on `selected_runner` at `odds`,
        such that resulting positions (profit if a runner wins, from bettor's
        perspective) stay within configured limits.

        `current_bettor_position` maps runner -> bettor's current net profit/loss
        if that runner wins (i.e. their existing exposure vector). Missing entries
        are treated as 0.

        Bounds depend on whether the *outcome runner* is the bettor themselves
        ("self") or another player ("others") - not on who the bet was placed on.
        A bet on any runner affects the bettor's position on every other runner
        too (mutually exclusive market), so all known runners must be checked.
        """

        current_bettor_position = self.compute_position(bettor)
        # Universe of runners whose position could be affected / constrained.
        # We must at least consider selected_runner and bettor themselves, plus
        # anything already tracked in the position dict.

        def position_bounds(runner: str) -> tuple[float, float]:
            if runner == bettor:
                return (
                    -self.model_settings.max_loss_self,
                    self.model_settings.max_profit_self,
                )
            if bet_type == BetType.LAY:
                return (
                    -self.model_settings.max_loss_non_self,
                    self.model_settings.max_profit_self,
                )
            return (
                -self.model_settings.max_loss_non_self,
                self.model_settings.max_profit_non_self,
            )

        max_stake = float("inf")
        decimal_odds = odds.decimal

        for runner in self.all_runners:
            pos = current_bettor_position.get(runner, 0.0)
            lower, upper = position_bounds(runner)

            if runner == selected_runner:
                if bet_type == BetType.BACK:
                    # Winning outcome: profit increases by S * (odds - 1)
                    allowed = (upper - pos) / (decimal_odds - 1)
                else:  # LAY
                    # Winning outcome: position decreases by S
                    allowed = pos - lower
            else:
                if bet_type == BetType.BACK:
                    # Any other runner winning: position decreases by S (stake lost)
                    allowed = pos - lower
                else:  # LAY
                    # Any other runner winning: position increases by S * (odds - 1)
                    allowed = (upper - pos) * (decimal_odds - 1)

            max_stake = min(max_stake, allowed)

        return round(max(0.0, max_stake), 2)
