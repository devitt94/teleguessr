from typing import Callable
from models import ActiveRound, RoundResult
import json
from pathlib import Path
from pydantic import BaseModel, Field

from settings import NUM_ROUNDS_PER_LEAGUE


ScoreManager = Callable[[RoundResult], dict[str, int]]


def default_score_manager(result: RoundResult) -> dict[str, int]:
    scores: dict[str, int] = {}
    for round_score in result.scores:
        scores[round_score.player.name] = round_score.net_score
    return scores


def ranking_score_manager(result: RoundResult) -> dict[str, int]:
    sorted_scores = sorted(result.scores, key=lambda rs: rs.net_score, reverse=True)
    scores: dict[str, int] = {}
    for rank, round_score in enumerate(sorted_scores, start=1):
        scores[round_score.player.name] = len(sorted_scores) - rank + 1
    return scores


class LeagueState(BaseModel):
    filepath: Path = Field(frozen=True)
    num_rounds: int = Field(default=NUM_ROUNDS_PER_LEAGUE)
    results: list[RoundResult] = Field(default_factory=list)
    current_round: ActiveRound | None = None

    def __init__(self, **data):
        super().__init__(**data)
        self.__scores: dict[str, int] = {}

    def load_from_file(self):
        try:
            with self.filepath.open("r") as f:
                file_data = json.load(f)
        except FileNotFoundError:
            return

        file_data["filepath"] = str(self.filepath)  # re-add frozen field
        loaded = LeagueState.model_validate(file_data)
        self.num_rounds = loaded.num_rounds

        self.__scores.clear()
        for result in loaded.results:
            self.add_round_result(result)

        self.current_round = loaded.current_round

    @property
    def current_round_num(self) -> int:
        return len(self.results) + 1 if self.round_in_progress else len(self.results)

    @property
    def is_finished(self) -> bool:
        return len(self.results) >= self.num_rounds

    @property
    def round_in_progress(self) -> bool:
        return self.current_round is not None

    @property
    def leaderboard(self) -> dict[str, int]:
        return self.__scores

    @property
    def winner(self) -> str | None:
        if not self.is_finished:
            return None
        if not self.__scores:
            return None
        return max(self.__scores, key=self.__scores.get)

    def start_round(self, url: str, hours: int):
        if self.round_in_progress:
            raise ValueError("A round is already in progress.")
        if self.is_finished:
            raise ValueError("The league has already finished.")
        from datetime import datetime, timedelta

        end_time = datetime.utcnow() + timedelta(hours=hours)
        self.current_round = ActiveRound(challenge_url=url, end_time=end_time)

    def add_round_result(self, result: RoundResult):
        self.results.append(result)
        added_scores = ranking_score_manager(result)
        for player, score in added_scores.items():
            self.__scores[player] = self.__scores.get(player, 0) + score

        if result.awards is not None:
            best_guess_player = result.awards.best_guess.player.name
            worst_guess_player = result.awards.worst_guess.player.name
            self.__scores[best_guess_player] = (
                self.__scores.get(best_guess_player, 0) + 1
            )
            self.__scores[worst_guess_player] = (
                self.__scores.get(worst_guess_player, 0) - 1
            )

        self.current_round = None

    def save(self):
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump_json(exclude=["filepath"], indent=2)
        with open(self.filepath, "w") as f:
            f.write(data)
