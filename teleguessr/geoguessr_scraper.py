from teleguessr.models import (
    Guess,
    Player,
    ChallengeResult,
    ChallengeScore,
    ChallengeSettings,
)

from geoguessr_async import Geoguessr, GeoguessrScore

from loguru import logger


class GeoguessrClient:
    def __init__(self, ncfa_cookie: str):
        self.ncfa_cookie = ncfa_cookie

    async def create_challenge(
        self,
        challenge_settings: ChallengeSettings,
    ) -> str:
        """
        Create a new GeoGuessr challenge and return its URL.
        """
        logger.info(
            f"Creating challenge for map_id={challenge_settings.map_id} with time_limit_seconds={challenge_settings.time_limit_seconds} and move_allowed={challenge_settings.move_allowed} and pan_allowed={challenge_settings.pan_allowed} and zoom_allowed={challenge_settings.zoom_allowed}"
        )

        map_url = f"https://www.geoguessr.com/maps/{challenge_settings.map_id}"
        challenge_url = await Geoguessr(self.ncfa_cookie).generate_challenge(
            mapUrl=map_url,
            move=challenge_settings.move_allowed,
            pan=challenge_settings.pan_allowed,
            zoom=challenge_settings.zoom_allowed,
            timeLimit=challenge_settings.time_limit_seconds,
            playMap=False,
            numRounds=challenge_settings.number_of_locations,
        )
        return challenge_url

    async def get_challenge_scores(
        self,
        url: str,
        handicaps: dict[str, float],
        default_handicap: float,
        challenge_settings: ChallengeSettings | None = None,
    ) -> ChallengeResult:
        """
        Scrape player names and scores from a GeoGuessr challenge page.
        (Assumes the challenge is public.)
        """

        geoguessr_scores: list[GeoguessrScore] = await Geoguessr(
            self.ncfa_cookie
        ).get_challenge_score(url)
        challenge_scores: list[ChallengeScore] = []
        for geoguessr_score in geoguessr_scores:
            playername = geoguessr_score.gamePlayerNick

            hcap_multiplier = handicaps.get(playername, default_handicap)

            guess_points = geoguessr_score.gamePlayerGuessesRoundScoreInPoints
            guess_distances = geoguessr_score.gamePlayerGuessesDistanceInMeters
            guesses = [
                Guess(score=score, distance_km=distance / 1000)
                for score, distance in zip(guess_points, guess_distances)
            ]

            player = Player(name=playername, hcap_multiplier=hcap_multiplier)
            round_score = ChallengeScore(player=player, guesses=guesses)
            challenge_scores.append(round_score)

        return ChallengeResult(
            challenge_url=url,
            scores=challenge_scores,
            challenge_settings=challenge_settings,
        )
