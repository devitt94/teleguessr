from datetime import datetime, date
from pydantic import BaseModel, Field, confloat, conlist


MAX_ROUND_SCORE = 5000


class Guess(BaseModel):
    score: int
    distance_km: float


class Player(BaseModel):
    name: str
    hcap_multiplier: confloat(ge=0.0, le=1.0)


class ChallengeSettings(BaseModel):
    map_id: str
    time_limit_seconds: int
    pan_allowed: bool
    zoom_allowed: bool
    move_allowed: bool
    number_of_locations: int = 5


class ActiveRound(BaseModel):
    challenge_url: str
    challenge_settings: ChallengeSettings
    end_time: datetime
    players_finished: list[str] = Field(default_factory=list)
    reminder_sent: bool = False


class ChallengeScore(BaseModel):
    player: Player
    guesses: list[Guess] = conlist(Guess, min_length=1)
    num_rounds: int = Field(default=10, ge=1)

    @property
    def is_finished(self) -> bool:
        return len(self.guesses) == self.num_rounds

    @property
    def gross_score(self) -> int:
        return sum(guess.score for guess in self.guesses)

    def compute_uncapped_hcap_adjustment(self, num_rounds: int) -> int:
        max_challenge_score = MAX_ROUND_SCORE * num_rounds
        return int(
            self.player.hcap_multiplier * (max_challenge_score - self.gross_score)
        )

    def compute_hcap_adjustment(self) -> int:
        uncapped_adjustment = self.compute_uncapped_hcap_adjustment(
            num_rounds=len(self.guesses)
        )
        max_adjustment = int(
            ((MAX_ROUND_SCORE * self.num_rounds) // 2) * self.player.hcap_multiplier
        )
        capped_adjustment = min(uncapped_adjustment, max_adjustment)
        return capped_adjustment

    def compute_net_score(self) -> int:
        return self.gross_score + self.compute_hcap_adjustment()


class GuessStats(BaseModel):
    average_distance: float
    median_distance: float
    stddev_distance: float
    average_pts: float
    median_pts: float
    stddev_pts: float
    second_best_pts: int
    second_worst_pts: int
    n_players: int


class Award(BaseModel):
    player: Player
    guess: Guess
    round_stats: GuessStats
    location_index: int


class RankedGuess(BaseModel):
    player: Player
    guess: Guess
    guess_stats: GuessStats
    location_index: int
    adjusted_score: float


class ChallengeResult(BaseModel):
    challenge_url: str
    scores: list[ChallengeScore] = conlist(ChallengeScore, min_length=1)
    ranked_guesses: list[RankedGuess] | None = None
    challenge_settings: ChallengeSettings | None = None

    @property
    def players_finished(self) -> set[str]:
        return {score.player.name for score in self.scores if score.is_finished}

    @property
    def num_rounds(self) -> int:
        return (
            self.challenge_settings.number_of_locations
            if self.challenge_settings
            else max(len(score.guesses) for score in self.scores if score.is_finished)
        )

    def get_player_position(self, player_name: str) -> int:
        sorted_scores = sorted(
            self.scores,
            key=lambda rs: rs.compute_net_score(),
            reverse=True,
        )
        for index, rs in enumerate(sorted_scores):
            if rs.player.name == player_name:
                return index + 1

        return -1


class AbbreviatedRoundScore(BaseModel):
    rank: int
    net_score: int
    rounds_played: int
    total_rounds: int

    @property
    def is_finished(self) -> bool:
        return self.rounds_played == self.total_rounds


class Bet(BaseModel):
    bettor: str
    runner: str
    stake: float
    odds: float

    @property
    def potential_profit(self) -> float:
        return self.stake * (self.odds - 1)

    @property
    def potential_return(self) -> float:
        return self.stake * self.odds

    def __str__(self):
        return (
            f"Bettor: {self.bettor}\n"
            f"Runner: {self.runner}\n"
            f"Stake: €{self.stake:.2f}\n"
            f"Odds: {self.odds:.2f}\n"
            f"Return: €{self.potential_return:.2f}\n"
            f"Potential Profit: €{self.potential_profit:.2f}\n"
        )


class Records(BaseModel):
    net_wins: int
    gross_wins: int
    most_recent_net_win: date | None = None
    most_recent_gross_win: date | None = None
