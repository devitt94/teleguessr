from pathlib import Path
from models import Guess, Player, RoundResult, RoundScore
from bs4 import BeautifulSoup


async def scrape_challenge_scores(url: str) -> RoundResult:
    """
    Scrape player names and scores from a GeoGuessr challenge page.
    (Assumes the challenge is public.)
    """

    filepath = Path("data/geoguessr_round_1.html")

    with filepath.open("r", encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")

    # Each player is in a div with class "coordinate-results_row__xhPGb"
    rows = soup.select("div.coordinate-results_row__xhPGb")

    player_scores = []
    for row in rows:
        # skip header rows
        if row.select_one(".coordinate-results_headerRow__GCyDD"):
            continue

        name = row.select_one(".user-nick_nick__sRjZ2")

        if not name:
            continue  # skip rows without a name

        # Each round's score
        round_scores = [
            int(r.get_text(strip=True).replace(" pts", "").replace(",", ""))
            for r in row.select(".score-cell_score__oKM2x")
        ][:-1]  # Exclude total score cell

        round_distances = [
            int(r.get_text(strip=True).replace(" km", "").replace(",", ""))
            for r in row.select(".score-cell_scoreDetails__D_Ygp > span:first-child")
        ][:-1]

        guesses = [
            Guess(score=score, distance_km=distance)
            for score, distance in zip(round_scores, round_distances)
        ]

        score = RoundScore(
            player=Player(name=name.get_text(strip=True)), guesses=guesses
        )
        player_scores.append(score)

    return RoundResult(challenge_url=url, scores=player_scores)
