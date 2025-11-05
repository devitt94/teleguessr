from datetime import datetime
from pydantic import BaseModel, conlist


class Guess(BaseModel):
    score: int
    distance_km: float


class Player(BaseModel):
    name: str
    round_hcap: int = 0


class ActiveRound(BaseModel):
    challenge_url: str
    end_time: datetime


class RoundScore(BaseModel):
    player: Player
    guesses: list[Guess] = conlist(Guess, min_length=1)

    @property
    def gross_score(self) -> int:
        return sum(guess.score for guess in self.guesses)

    @property
    def net_score(self) -> int:
        return self.gross_score + self.player.round_hcap


class GuessStats(BaseModel):
    average_distance: float
    stddev_distance: float
    average_pts: float
    stddev_pts: float


class Award(BaseModel):
    player: Player
    guess: Guess
    round_stats: GuessStats
    location_index: int


class Awards(BaseModel):
    best_guess: Award
    worst_guess: Award


class RoundResult(BaseModel):
    challenge_url: str
    scores: list[RoundScore] = conlist(RoundScore, min_length=1)
    awards: Awards | None = None
