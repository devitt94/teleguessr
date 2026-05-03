from datetime import datetime
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

    @property
    def gross_score(self) -> int:
        return sum(guess.score for guess in self.guesses)

    def compute_uncapped_hcap_adjustment(self, num_rounds: int) -> int:
        max_challenge_score = MAX_ROUND_SCORE * num_rounds
        return int(
            self.player.hcap_multiplier * (max_challenge_score - self.gross_score)
        )

    def compute_hcap_adjustment(self, num_rounds: int) -> int:
        uncapped_adjustment = self.compute_uncapped_hcap_adjustment(
            num_rounds=num_rounds
        )
        max_adjustment = int(
            ((MAX_ROUND_SCORE * num_rounds) // 2) * self.player.hcap_multiplier
        )
        return min(uncapped_adjustment, max_adjustment)

    def compute_net_score(self, num_rounds: int) -> int:
        return self.gross_score + self.compute_hcap_adjustment(num_rounds=num_rounds)


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
    challenge_settings: ChallengeSettings | None = None

    @property
    def players_finished(self) -> set[str]:
        return {score.player.name for score in self.scores}

    @property
    def num_rounds(self) -> int:
        return (
            self.challenge_settings.number_of_locations
            if self.challenge_settings
            else max(len(score.guesses) for score in self.scores)
        )

    def get_player_position(self, player_name: str) -> int:
        sorted_scores = sorted(
            self.scores,
            key=lambda rs: rs.compute_net_score(self.num_rounds),
            reverse=True,
        )
        for index, rs in enumerate(sorted_scores):
            if rs.player.name == player_name:
                return index + 1

        return -1


class AbbreviatedRoundScore(BaseModel):
    rank: int
    net_score: int


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
