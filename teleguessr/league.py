from collections import defaultdict
from datetime import datetime
from typing import Callable
from teleguessr.models import ActiveRound, ChallengeResult, RankedGuess
import json
from pathlib import Path
from pydantic import BaseModel, Field


ScoreManager = Callable[[ChallengeResult], dict[str, int]]


def default_score_manager(result: ChallengeResult) -> dict[str, int]:
    scores: dict[str, int] = {}
    for round_score in result.scores:
        scores[round_score.player.name] = round_score.net_score
    return scores


def ranking_score_manager(result: ChallengeResult) -> dict[str, int]:
    sorted_scores = sorted(result.scores, key=lambda rs: rs.net_score, reverse=True)
    scores: dict[str, int] = {}
    for rank, round_score in enumerate(sorted_scores, start=1):
        scores[round_score.player.name] = len(sorted_scores) - rank + 1
    return scores


def skewed_ranking_score_manager(result: ChallengeResult) -> dict[str, int]:
    # 1st: 12 points, 2nd: 10 points, 3rd: 8 points, 4th: 7 points, ..., 10th: 1 point
    rank_points = [12, 10, 8, 7, 6, 5, 4, 3, 2, 1]
    sorted_scores = sorted(result.scores, key=lambda rs: rs.net_score, reverse=True)
    scores: dict[str, int] = {}
    for rank, round_score in enumerate(sorted_scores):
        if rank < len(rank_points):
            scores[round_score.player.name] = rank_points[rank]
        else:
            scores[round_score.player.name] = 1
    return scores


class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()


class LeagueState(BaseModel):
    num_rounds: int
    filepath: Path = Field(frozen=True)
    results: list[ChallengeResult] = Field(default_factory=list)
    chat_id: int | None = None
    current_round: ActiveRound | None = None

    def __init__(self, **data):
        super().__init__(**data)
        self.__scores: dict[str, int] = {}
        self.__best_guesses_by_player: dict[str, int] = defaultdict(int)
        self.__worst_guesses_by_player: dict[str, int] = defaultdict(int)
        self.__round_results_by_player: dict[str, dict[int, int]] = defaultdict(dict)

    def load_from_file(self):
        try:
            with self.filepath.open("r") as f:
                file_data = json.load(f)
        except FileNotFoundError:
            return

        file_data["filepath"] = str(self.filepath)  # re-add frozen field
        loaded = LeagueState.model_validate(file_data)
        self.num_rounds = loaded.num_rounds
        self.chat_id = loaded.chat_id

        self.results = loaded.results
        self.__best_guesses_by_player = defaultdict(
            int, file_data.get("best_guesses_by_player", {})
        )
        self.__worst_guesses_by_player = defaultdict(
            int, file_data.get("worst_guesses_by_player", {})
        )
        self.__round_results_by_player = defaultdict(
            dict, file_data.get("round_results_by_player", {})
        )
        self.__scores = file_data.get("scores", {})

        self.current_round = loaded.current_round

    @property
    def current_round_num(self) -> int:
        return len(self.results) + 1 if self.round_in_progress else len(self.results)

    @property
    def last_round_finished_num(self) -> int:
        if self.results:
            return len(self.results)
        return 0

    @property
    def is_finished(self) -> bool:
        return len(self.results) >= self.num_rounds

    @property
    def round_in_progress(self) -> bool:
        return self.current_round is not None

    @property
    def league_id(self) -> int:
        return int(self.filepath.stem.split("_")[-1])

    def construct_leaderboard(self) -> dict[int, list[str]]:
        """Returns a mapping of rank to list of player names at that rank."""
        rank_map: dict[int, list[str]] = defaultdict(list)
        sorted_scores = sorted(self.__scores.items(), key=lambda x: x[1], reverse=True)
        current_rank = 1
        last_score = None
        for player, score in sorted_scores:
            if last_score is None or score < last_score:
                rank_map[current_rank].append(player)
                last_score = score
            else:
                rank_map[current_rank - 1].append(player)
            current_rank += 1

        return dict(rank_map)

    def get_leaderboard_data(self) -> dict[str, dict]:
        return {
            "leaderboard": self.construct_leaderboard(),
            "best_guesses": self.__best_guesses_by_player,
            "worst_guesses": self.__worst_guesses_by_player,
            "round_positions": self.__round_results_by_player,
            "scores": self.__scores,
            "rounds_played": self.last_round_finished_num or 0,
        }

    def get_winner(self) -> str:
        if not self.is_finished:
            raise ValueError("League is not finished yet.")
        if not self.__scores:
            raise ValueError("No scores available to determine a winner.")

        # For tie bre
        if not self.is_finished:
            raise ValueError("League is not finished yet.")
        if not self.__scores:
            raise ValueError("No scores available to determine a winner.")

        # For tie breakers, the player who had the best score in the last round wins.
        sorted_leaderboard = sorted(
            self.__scores.items(), key=lambda x: x[1], reverse=True
        )
        top_score = sorted_leaderboard[0][1]
        top_players = [p for p, s in sorted_leaderboard if s == top_score]
        if len(top_players) == 1:
            return top_players[0]

        last_round = self.results[-1]
        last_round_scores = {rs.player.name: rs.net_score for rs in last_round.scores}
        top_players_sorted = sorted(
            top_players, key=lambda p: last_round_scores.get(p, 0), reverse=True
        )
        return top_players_sorted[0]

    def start_round(self, url: str, hours: int):
        if self.round_in_progress:
            raise ValueError("A round is already in progress.")
        if self.is_finished:
            raise ValueError("The league has already finished.")
        from datetime import datetime, timedelta

        end_time = datetime.utcnow() + timedelta(hours=hours)
        self.current_round = ActiveRound(
            challenge_url=url, end_time=end_time, players_finished=set()
        )

    def add_round_result(self, result: ChallengeResult):
        self.results.append(result)
        added_scores = skewed_ranking_score_manager(result)
        for player, score in added_scores.items():
            self.__scores[player] = self.__scores.get(player, 0) + score
            self.__round_results_by_player[player][str(self.current_round_num - 1)] = (
                result.get_player_position(player)
            )

        self.current_round = None

    def add_awards(self, best_guess: RankedGuess, worst_guess: RankedGuess):
        best_guess_player = best_guess.player.name
        worst_guess_player = worst_guess.player.name
        self.__scores[best_guess_player] = self.__scores.get(best_guess_player, 0) + 1
        self.__scores[worst_guess_player] = self.__scores.get(worst_guess_player, 0) - 1

        self.__best_guesses_by_player[best_guess_player] += 1
        self.__worst_guesses_by_player[worst_guess_player] += 1

    def save(self):
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(exclude=["filepath"])
        data["scores"] = self.__scores
        data["best_guesses_by_player"] = dict(self.__best_guesses_by_player)
        data["worst_guesses_by_player"] = dict(self.__worst_guesses_by_player)
        data["round_results_by_player"] = dict(self.__round_results_by_player)

        with open(self.filepath, "w") as f:
            f.write(json.dumps(data, indent=2, cls=JSONEncoder))

    def get_time_left_seconds(self) -> int:
        if not self.round_in_progress:
            return 0
        from datetime import datetime

        now = datetime.now(self.current_round.end_time.tzinfo)
        delta = self.current_round.end_time - now
        return max(0, int(delta.total_seconds()))

    def add_player_finished(self, player_name: str):
        if not self.round_in_progress:
            raise ValueError("No round is currently in progress.")
        self.current_round.players_finished.append(player_name)

    def get_players_finished_round(self) -> set[str]:
        if not self.round_in_progress:
            return set()
        return set(self.current_round.players_finished)
