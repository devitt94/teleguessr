from functools import lru_cache
from pathlib import Path
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

NEW_ENTRANT_HANDICAP_MULTIPLIER = 0.25
MAXIMUM_HANDICAP_MULTIPLIER = 0.30


class LeagueSettings(BaseModel):
    map_id: str
    number_of_rounds: int = 5
    time_per_round_hours: int = 24
    time_per_guess_seconds: int = 90

    handicaps_dir: Path = Path("data/handicaps/")

    default_handicap_multiplier: float = NEW_ENTRANT_HANDICAP_MULTIPLIER

    max_handicap_multiplier: float = MAXIMUM_HANDICAP_MULTIPLIER


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
