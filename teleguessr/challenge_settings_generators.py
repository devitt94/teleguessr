from typing import Protocol

from teleguessr.models import ChallengeSettings


CLASSIC_WORLD_MAP_ID = "WORLD"
COMMUNITY_WORLD_MAP_ID = "62a44b22040f04bd36e8a914"


class ChallengeSettingsGenerator(Protocol):
    def __call__(self, round_number: int) -> ChallengeSettings:
        """
        Generate challenge settings for a given round number.
        """
        ...


def classic_challenge_settings_generator(
    round_number: int, number_of_locations: int = 5
) -> ChallengeSettings:
    """
    Original challenge settings generator used in the first few leagues. Always returns the same settings.
    90 seconds, community world map, no move.
    """

    return ChallengeSettings(
        time_limit_seconds=90,
        map_id=COMMUNITY_WORLD_MAP_ID,
        pan_allowed=True,
        zoom_allowed=True,
        move_allowed=False,
        number_of_locations=number_of_locations,
    )


def mixed_challenge_settings_generator(round_number: int) -> ChallengeSettings:
    """
    New challenge settings generator that could be used for future leagues. For now, it returns the same settings as the classic generator, but it could be easily modified to return different settings for different rounds.
    """

    if round_number == 1:
        return ChallengeSettings(
            time_limit_seconds=180,
            map_id=COMMUNITY_WORLD_MAP_ID,
            pan_allowed=True,
            zoom_allowed=True,
            move_allowed=True,
            number_of_locations=5,
        )
    elif round_number == 3:
        return ChallengeSettings(
            time_limit_seconds=10,
            map_id=COMMUNITY_WORLD_MAP_ID,
            pan_allowed=True,
            zoom_allowed=True,
            move_allowed=False,
            number_of_locations=10,
        )
    else:
        return classic_challenge_settings_generator(
            round_number, number_of_locations=10
        )
