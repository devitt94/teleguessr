from datetime import datetime
from pydantic import BaseModel, Field, confloat, conlist


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
    players_finished: list[str] = Field(default_factory=list)
    reminder_sent: bool = False


class ChallengeScore(BaseModel):
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
    median_distance: float
    stddev_distance: float
    average_pts: float
    median_pts: float
    stddev_pts: float
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

    @property
    def players_finished(self) -> set[str]:
        return {score.player.name for score in self.scores}

    def get_player_position(self, player_name: str) -> int:
        sorted_scores = sorted(self.scores, key=lambda rs: rs.net_score, reverse=True)
        for index, rs in enumerate(sorted_scores):
            if rs.player.name == player_name:
                return index + 1

        return -1


class AbbreviatedRoundScore(BaseModel):
    rank: int
    net_score: int
