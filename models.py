from datetime import datetime
from pydantic import BaseModel, confloat, conlist


MAX_ROUND_SCORE = 25_000

class Guess(BaseModel):
    score: int
    distance_km: float


class Player(BaseModel):
    name: str
    hcap_multiplier: confloat(ge=0.0, le=1.0)


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
    def hcap_adjustment(self) -> int:
        return int(self.player.hcap_multiplier * (MAX_ROUND_SCORE - self.gross_score))
        
    @property
    def net_score(self) -> int:
        return self.gross_score + self.hcap_adjustment


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


    @property
    def players_finished(self) -> set[str]:
        return {score.player.name for score in self.scores}