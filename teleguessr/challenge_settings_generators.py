from typing import Protocol
import random
from teleguessr.models import ChallengeSettings


CLASSIC_WORLD_MAP_ID = "WORLD"
COMMUNITY_WORLD_MAP_ID = "62a44b22040f04bd36e8a914"
MOVING_WORLD_MAP_ID = "696fe47c5b07bed052077a95"
URBAN_WORLD_MAP_ID = "640d01bf1b14982128374759"
ARBITRARY_WORLD_MAP_ID = "6089bfcff6a0770001f645dd"
PINPOINTABLE_WORLD_MAP_ID = "6029991c5048850001d572a9"
I_SAW_THE_SIGN_MAP_ID = "5cfda2c9bc79e16dd866104d"
CAPITALS_OF_THE_WORLD_MAP_ID = "60de2a8a81b92c00015f29e1"
GEODETECTIVE_MAP_ID = "5d374dc141d2a43c1cd4527b"
VARIED_WORLD_MAP_ID = "64ce812adc7614680516ff8c"
DRONE_WORLD_MAP_ID = "5ffdf324d32ba4000169ff6e"
ABANDONED_PLACES_MAP_ID = "5e8cafac2ad6cf626cd89384"
UNESCO_WORLD_HERITAGE_SITES_MAP_ID = "5ad0b0cb2a3e0d4da46cc44c"
DIVERSE_COMPLETE_WORLD_MAP_ID = "5ff7033214a99c00012fe738"


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
    if round_number == 1:
        map_id = random.choice(
            [
                ARBITRARY_WORLD_MAP_ID,
                PINPOINTABLE_WORLD_MAP_ID,
                I_SAW_THE_SIGN_MAP_ID,
                CAPITALS_OF_THE_WORLD_MAP_ID,
                GEODETECTIVE_MAP_ID,
                VARIED_WORLD_MAP_ID,
                DRONE_WORLD_MAP_ID,
                ABANDONED_PLACES_MAP_ID,
                UNESCO_WORLD_HERITAGE_SITES_MAP_ID,
                DIVERSE_COMPLETE_WORLD_MAP_ID,
            ]
        )
        return ChallengeSettings(
            time_limit_seconds=90,
            map_id=map_id,
            pan_allowed=True,
            zoom_allowed=True,
            move_allowed=False,
            number_of_locations=10,
        )
    elif round_number == 3:
        return ChallengeSettings(
            time_limit_seconds=15,
            map_id=COMMUNITY_WORLD_MAP_ID,
            pan_allowed=False,
            zoom_allowed=False,
            move_allowed=False,
            number_of_locations=10,
        )
    else:
        return classic_challenge_settings_generator(
            round_number, number_of_locations=10
        )


def test_challenge_settings_generator(round_number: int) -> ChallengeSettings:
    """
    Challenge settings generator for testing purposes.
    """

    return ChallengeSettings(
        time_limit_seconds=15,
        map_id=COMMUNITY_WORLD_MAP_ID,
        pan_allowed=False,
        zoom_allowed=False,
        move_allowed=False,
        number_of_locations=2,
    )


CHALLENGE_SETTINGS: dict[str, ChallengeSettingsGenerator] = {
    "CLASSIC": classic_challenge_settings_generator,
    "MIXED": mixed_challenge_settings_generator,
    "TEST": test_challenge_settings_generator,
}
