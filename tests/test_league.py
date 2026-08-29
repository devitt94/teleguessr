import pytest

from teleguessr.league import skewed_ranking_score_manager


class FakePlayer:
    def __init__(self, name: str):
        self.name = name


class FakeChallengeScore:
    def __init__(self, player: str, net_score: int):
        self.player = FakePlayer(player)
        self.net_score = net_score

    def compute_net_score(self) -> int:
        return self.net_score


class FakeChallengeResult:
    def __init__(self, scores: list[FakeChallengeScore]):
        self.scores = scores


def make_result(scores: dict[str, int]) -> FakeChallengeResult:
    return FakeChallengeResult(
        scores=[
            FakeChallengeScore(player=name, net_score=score)
            for name, score in scores.items()
        ]
    )


@pytest.mark.parametrize(
    ("scores", "expected"),
    [
        (
            {"player1": 10, "player2": 20, "player3": 15, "player4": 5, "player5": 3},
            {"player2": 10, "player3": 7, "player1": 5, "player4": 3, "player5": 1},
        ),
        (
            {f"player{i}": i for i in range(1, 11)},
            {
                "player10": 15,
                "player9": 12,
                "player8": 10,
                "player7": 8,
                "player6": 7,
                "player5": 6,
                "player4": 5,
                "player3": 4,
                "player2": 3,
                "player1": 1,
            },
        ),
    ],
)
def test_skewed_ranking_score_manager(scores, expected):
    result = make_result(scores)
    num_players = len(scores)
    assert skewed_ranking_score_manager(result, num_players) == expected
