from models import ActiveRound, RoundResult
import json
from pathlib import Path
from pydantic import BaseModel, Field


class LeagueState(BaseModel):
    filepath: Path = Field(frozen=True)
    num_rounds: int = Field(default=5)
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
        self.results = loaded.results
        self.current_round = loaded.current_round
        self.num_rounds = loaded.num_rounds

        # Recalculate scores
        self.__scores.clear()
        for result in self.results:
            for player_score in result.scores:
                prev_score = self.__scores.get(player_score.player.name, 0)
                new_score = prev_score + player_score.total_score
                self.__scores[player_score.player.name] = new_score

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
        for player_score in result.scores:
            prev_score = self.__scores.get(player_score.player.name, 0)
            new_score = prev_score + player_score.total_score
            self.__scores[player_score.player.name] = new_score

        self.current_round = None

    def save(self):
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump_json(exclude=["filepath"], indent=2)
        with open(self.filepath, "w") as f:
            f.write(data)
