import os
from models import Guess, Player, RoundResult, RoundScore


from geoguessr_async import Geoguessr, GeoguessrScore
from settings import NEW_ENTRANT_HANDICAP_MULTIPLIER, PLAYER_HANDICAP_MULTIPLIERS


MAX_ROUND_SCORE = 25_000


async def create_challenge(
    map_id: str,
    time_limit_seconds: int,
) -> str:
    """
    Create a new GeoGuessr challenge and return its URL.
    """

    map_url = f"https://www.geoguessr.com/maps/{map_id}"
    client = Geoguessr(os.getenv("NCFA_COOKIE"))
    challenge_url = await client.generate_challenge(
        map_url=map_url,
        move=False,
        pan=True,
        zoom=True,
        timeLimit=time_limit_seconds,
        play_map=False,
    )
    return challenge_url


async def get_challenge_scores(url: str) -> RoundResult:
    """
    Scrape player names and scores from a GeoGuessr challenge page.
    (Assumes the challenge is public.)
    """

    client = Geoguessr(os.getenv("NCFA_COOKIE"))

    geoguessr_scores: list[GeoguessrScore] = await client.get_challenge_score(url)
    challenge_scores: list[RoundScore] = []
    for geoguessr_score in geoguessr_scores:
        playername = geoguessr_score.gamePlayerNick
        # round_hcap = PLAYER_ROUND_HANDICAPS.get(playername, NEW_ENTRANT_HANDICAP)

        hcap_multiplier = PLAYER_HANDICAP_MULTIPLIERS.get(
            playername, NEW_ENTRANT_HANDICAP_MULTIPLIER
        )

        guess_points = geoguessr_score.gamePlayerGuessesRoundScoreInPoints
        guess_distances = geoguessr_score.gamePlayerGuessesDistanceInMeters
        guesses = [
            Guess(score=score, distance_km=distance // 1000)
            for score, distance in zip(guess_points, guess_distances)
        ]

        guess_total = sum(guess.score for guess in guesses)
        round_hcap = int(hcap_multiplier * (MAX_ROUND_SCORE - guess_total))

        player = Player(name=playername, round_hcap=round_hcap)
        round_score = RoundScore(player=player, guesses=guesses)
        challenge_scores.append(round_score)

    return RoundResult(challenge_url=url, scores=challenge_scores)
