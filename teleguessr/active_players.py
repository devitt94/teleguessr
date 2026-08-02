import json
from pathlib import Path


class PlayerManager:
    def __init__(self, data_dir: Path, initial_players: set[str] | None = None):
        self.active_player_file = data_dir / "active_players" / "active_players.json"
        if not self.active_player_file.exists():
            self.__save(initial_players or set())

    def __save(self, active_players: set[str]) -> None:
        self.active_player_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.active_player_file, "w") as f:
            json.dump(list(active_players), f, indent=4)

    def get_active_players(self) -> set[str]:
        if not self.active_player_file.exists():
            raise FileNotFoundError(
                f"Active player file not found: {self.active_player_file}"
            )

        with open(self.active_player_file, "r") as f:
            active_players = set(json.load(f))
        return active_players

    def add_active_player(self, player_name: str) -> bool:
        active_players = self.get_active_players()
        already_active = player_name in active_players
        active_players.add(player_name)
        self.__save(active_players)
        return not already_active

    def clear_active_players(self) -> None:
        self.__save(set())
