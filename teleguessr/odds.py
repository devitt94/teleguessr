from typing import NamedTuple


class FractionalOdds(NamedTuple):
    numerator: int
    denominator: int

    @property
    def decimal(self) -> float:
        return 1.0 + self.numerator / self.denominator

    @property
    def formatted(self) -> str:
        return f"{self.numerator}/{self.denominator}"

    @property
    def implied_probability(self) -> float:
        return 1.0 / self.decimal

    @classmethod
    def from_str(cls, odds_str: str) -> "FractionalOdds":
        try:
            numerator, denominator = map(int, odds_str.split("/"))
            return cls(numerator, denominator)
        except Exception as e:
            raise ValueError(f"Invalid fractional odds format: {odds_str}") from e


def probs_to_odds(
    probabilities: list[float],
) -> list[FractionalOdds | None]:
    """
    Convert a list of model probability estimates to fractional bookmaker odds,
    accounting for two independent sources of uncertainty:

      1. Sampling noise  -- covered by the SE margin (k * SE(p)), which is larger
                            for underdogs where the estimate is noisiest.
      2. Model error     -- covered by flat_margin, a percentage uplift applied to
                            all runners equally to guard against mis-specified inputs
                            or structural model errors.

    The two margins compound:
        adjusted_p = (p + k * SE(p)) * (1 + flat_margin)

    Args:
        probabilities:   List of win probabilities from your model (should sum to ~1.0).
        n_simulations:   Number of MC simulation runs used to produce the estimates.
        k:               Number of standard errors to add as SE margin (default 2.0,
                         i.e. roughly the 97.5th percentile of the sampling estimate).
        flat_margin:     Fractional uplift applied to all runners to cover model error
                         (default 0.05 = 5%). Use higher values if model inputs are
                         uncertain; lower if the model is well-validated.
        ladder:          Optional list of fractional odds tuples to round down to.
                         If None, rounds down to the nearest rung on BOOKMAKER_LADDER.

    Returns:
        List of fractional odds tuples (numerator, denominator),
        in the same order as the input probabilities.
    """
    return [probability_to_odds(p) for p in probabilities]


def probability_to_odds(probability: float) -> FractionalOdds | None:
    """Convert a single probability to fractional bookmaker odds."""

    if probability < 0 or probability > 1:
        raise ValueError("probability must be between 0 and 1")

    for prob, odds in BOOKMAKER_LADDER:
        if probability >= prob:
            return odds
    return None


# ---------------------------------------------------------------------------
# Standard fractional bookmaker odds ladder
# ---------------------------------------------------------------------------
BOOKMAKER_LADDER: tuple[tuple[float, FractionalOdds | None]] = (
    (0.995, None),  # no bet offered for almost certain outcomes
    (0.99, FractionalOdds(1, 1000)),
    (0.98, FractionalOdds(1, 500)),
    (0.97, FractionalOdds(1, 200)),
    (0.96, FractionalOdds(1, 100)),
    (0.95, FractionalOdds(1, 66)),
    (0.94, FractionalOdds(1, 50)),
    (0.93, FractionalOdds(1, 33)),
    (0.92, FractionalOdds(1, 25)),
    (0.91, FractionalOdds(1, 20)),
    (0.90, FractionalOdds(1, 18)),
    (0.89, FractionalOdds(1, 16)),
    (0.88, FractionalOdds(1, 14)),
    (0.87, FractionalOdds(1, 12)),
    (0.86, FractionalOdds(1, 10)),
    (0.85, FractionalOdds(1, 9)),
    (0.84, FractionalOdds(1, 8)),
    (0.83, FractionalOdds(2, 15)),
    (0.82, FractionalOdds(1, 7)),
    (0.81, FractionalOdds(2, 13)),
    (0.80, FractionalOdds(1, 6)),
    (0.79, FractionalOdds(2, 11)),
    (0.78, FractionalOdds(1, 5)),
    (0.76, FractionalOdds(2, 9)),
    (0.74, FractionalOdds(1, 4)),
    (0.72, FractionalOdds(2, 7)),
    (0.70, FractionalOdds(3, 10)),
    (0.68, FractionalOdds(1, 3)),
    (0.66, FractionalOdds(4, 11)),
    (0.64, FractionalOdds(2, 5)),
    (0.62, FractionalOdds(4, 9)),
    (0.60, FractionalOdds(1, 2)),
    (0.59, FractionalOdds(8, 15)),
    (0.57, FractionalOdds(4, 7)),
    (0.55, FractionalOdds(8, 13)),
    (0.53, FractionalOdds(4, 6)),
    (0.51, FractionalOdds(8, 11)),
    (0.50, FractionalOdds(4, 5)),
    (0.48, FractionalOdds(5, 6)),
    (0.47, FractionalOdds(10, 11)),
    (0.45, FractionalOdds(20, 21)),
    (0.44, FractionalOdds(1, 1)),
    (0.43, FractionalOdds(21, 20)),
    (0.42, FractionalOdds(11, 10)),
    (0.41, FractionalOdds(23, 20)),
    (0.40, FractionalOdds(6, 5)),
    (0.39, FractionalOdds(5, 4)),
    (0.38, FractionalOdds(13, 10)),
    (0.37, FractionalOdds(11, 8)),
    (0.36, FractionalOdds(7, 5)),
    (0.34, FractionalOdds(6, 4)),
    (0.325, FractionalOdds(13, 8)),
    (0.31, FractionalOdds(7, 4)),
    (0.295, FractionalOdds(15, 8)),
    (0.28, FractionalOdds(2, 1)),
    (0.265, FractionalOdds(21, 10)),
    (0.25, FractionalOdds(9, 4)),
    (0.235, FractionalOdds(12, 5)),
    (0.21, FractionalOdds(5, 2)),
    (0.20, FractionalOdds(11, 4)),
    (0.19, FractionalOdds(3, 1)),
    (0.18, FractionalOdds(13, 4)),
    (0.17, FractionalOdds(7, 2)),
    (0.16, FractionalOdds(15, 4)),
    (0.145, FractionalOdds(4, 1)),
    (0.13, FractionalOdds(9, 2)),
    (0.115, FractionalOdds(5, 1)),
    (0.10, FractionalOdds(11, 2)),
    (0.09, FractionalOdds(6, 1)),
    (0.08, FractionalOdds(13, 2)),
    (0.07, FractionalOdds(7, 1)),
    (0.06, FractionalOdds(15, 2)),
    (0.05, FractionalOdds(9, 1)),
    (0.04, FractionalOdds(10, 1)),
    (0.03, FractionalOdds(12, 1)),
    (0.02, FractionalOdds(14, 1)),
    (0.01, FractionalOdds(20, 1)),
    (0.005, FractionalOdds(33, 1)),
    (0.002, FractionalOdds(50, 1)),
    (0.001, FractionalOdds(66, 1)),
)
