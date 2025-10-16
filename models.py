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
    def total_score(self) -> int:
        return sum(guess.score for guess in self.guesses)


class RoundResult(BaseModel):
    challenge_url: str
    scores: list[RoundScore] = conlist(RoundScore, min_length=1)

