from models import Guess, Player, RoundResult, RoundScore
from settings import PLAYERS, NUM_GUESSES_PER_ROUND
import random

async def scrape_scores_fake(url: str) -> RoundResult:
    """
    Fake scraper for testing without hitting GeoGuessr.
    """
    players = [Player(**p) for p in PLAYERS]

    scores = []
    for p in players:
        p.round_hcap = 0  # Reset score for the round
        player_guesses = []
        for i in range(NUM_GUESSES_PER_ROUND):
            score = random.randint(0, 5000)
            distance = random.uniform(0, 20000)
            guess = Guess(score=score, distance_km=distance)
            player_guesses.append(guess)
            
        player_score = RoundScore(player=p, guesses=player_guesses)
        scores.append(player_score)
    return RoundResult(challenge_url=url, scores=scores)


async def scrape_challenge_scores(url: str):
    """
    Scrape player names and scores from a GeoGuessr challenge page.
    (Assumes the challenge is public.)
    """
    # results = {}
    # async with aiohttp.ClientSession() as session:
    #     async with session.get(url) as resp:
    #         html = await resp.text()

    # # ⚠️ This part depends on the actual GeoGuessr page structure.
    # # Example logic (pseudo-selector):
    # soup = BeautifulSoup(html, "html.parser")
    # for player_tag in soup.select(".player-result"):
    #     name = player_tag.select_one(".player-name").text.strip()
    #     score = int(player_tag.select_one(".player-score").text.replace(",", "").strip())
    #     results[name] = score

    # return results
