from functools import lru_cache
from pathlib import Path
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


PLAYER_HANDICAP_MULTIPLIERS = {
    "Bosnia & GetsTheGoldSweena": 0.0,
    "Grand Duchy of Gregdova": 0.0,
    "St. Bics & Devitts": 0.2,
    "Ppl's Rep. Glorious Mickistan": 0.2,
    "Danminican Republic": 0.2,
    "Ellitorial Guinea": 0.2,
    "Kingdom of Gregoria I": 0.2,
}

NEW_ENTRANT_HANDICAP_MULTIPLIER = 0.2

PLAYER_SHORTNAMES = {
    "Bosnia & GetsTheGoldSweena": "B&GGS",
    "Grand Duchy of Gregdova": "Gregdova",
    "Ppl's Rep. Glorious Mickistan": "Mickistan",
    "Danminican Republic": "Danminican",
    "St. Bics & Devitts": "St. Bics",
    "Kingdom of Gregoria I": "Gregoria",
}


class LeagueSettings(BaseModel):
    map_id: str
    number_of_rounds: int = 5
    time_per_round_hours: int = 24
    time_per_guess_seconds: int = 90


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_nested_delimiter="__"
    )

    telegram_bot_token: str
    telegram_admin_id: int
    geoguessr_ncfa_cookie: str
    data_dir: Path = Path("data/")
    league: LeagueSettings


@lru_cache()
def get_settings() -> AppSettings:
    return AppSettings()
