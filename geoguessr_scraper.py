import os
from models import Guess, Player, RoundResult, RoundScore


from geoguessr_async import Geoguessr, GeoguessrScore
from settings import PLAYER_ROUND_HANDICAPS


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
        round_hcap = PLAYER_ROUND_HANDICAPS.get(playername, 0)
        player = Player(name=playername, round_hcap=round_hcap)
        guess_points = geoguessr_score.gamePlayerGuessesRoundScoreInPoints
        guess_distances = geoguessr_score.gamePlayerGuessesDistanceInMeters
        guesses = [
            Guess(score=score, distance_km=distance // 1000)
            for score, distance in zip(guess_points, guess_distances)
        ]
        round_score = RoundScore(player=player, guesses=guesses)
        challenge_scores.append(round_score)

    return RoundResult(challenge_url=url, scores=challenge_scores)
