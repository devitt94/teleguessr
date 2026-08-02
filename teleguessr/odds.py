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

    def invert(self) -> "FractionalOdds":
        """Return the inverse of the odds (e.g., 2/1 becomes 1/2)."""
        return FractionalOdds(self.denominator, self.numerator)


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
    (0.999, None),  # no bet offered for almost certain outcomes
    (0.995, FractionalOdds(1, 1000)),
    (0.99, FractionalOdds(1, 500)),
    (0.98, FractionalOdds(1, 200)),
    (0.97, FractionalOdds(1, 100)),
    (0.96, FractionalOdds(1, 66)),
    (0.95, FractionalOdds(1, 50)),
    (0.94, FractionalOdds(1, 33)),
    (0.93, FractionalOdds(1, 25)),
    (0.92, FractionalOdds(1, 20)),
    (0.91, FractionalOdds(1, 18)),
    (0.90, FractionalOdds(1, 16)),
    (0.89, FractionalOdds(1, 14)),
    (0.885, FractionalOdds(1, 12)),
    (0.875, FractionalOdds(1, 10)),
    (0.865, FractionalOdds(1, 9)),
    (0.855, FractionalOdds(1, 8)),
    (0.845, FractionalOdds(1, 7)),
    (0.83, FractionalOdds(2, 13)),
    (0.82, FractionalOdds(1, 6)),
    (0.81, FractionalOdds(2, 11)),
    (0.795, FractionalOdds(1, 5)),
    (0.78, FractionalOdds(2, 9)),
    (0.765, FractionalOdds(1, 4)),
    (0.755, FractionalOdds(4, 15)),
    (0.74, FractionalOdds(2, 7)),
    (0.73, FractionalOdds(3, 10)),
    (0.72, FractionalOdds(1, 3)),
    (0.71, FractionalOdds(7, 20)),
    (0.70, FractionalOdds(4, 11)),
    (0.685, FractionalOdds(3, 8)),
    (0.67, FractionalOdds(2, 5)),
    (0.66, FractionalOdds(4, 9)),
    (0.645, FractionalOdds(7, 15)),
    (0.63, FractionalOdds(1, 2)),
    (0.615, FractionalOdds(8, 15)),
    (0.5975, FractionalOdds(4, 7)),
    (0.58, FractionalOdds(8, 13)),
    (0.565, FractionalOdds(4, 6)),
    (0.55, FractionalOdds(7, 10)),
    (0.535, FractionalOdds(8, 11)),
    (0.5175, FractionalOdds(4, 5)),
    (0.5025, FractionalOdds(5, 6)),
    (0.49, FractionalOdds(10, 11)),
    (0.475, FractionalOdds(20, 21)),
    (0.465, FractionalOdds(1, 1)),
    (0.45, FractionalOdds(21, 20)),
    (0.4375, FractionalOdds(11, 10)),
    (0.425, FractionalOdds(23, 20)),
    (0.415, FractionalOdds(6, 5)),
    (0.405, FractionalOdds(5, 4)),
    (0.395, FractionalOdds(13, 10)),
    (0.385, FractionalOdds(11, 8)),
    (0.375, FractionalOdds(7, 5)),
    (0.36, FractionalOdds(6, 4)),
    (0.34, FractionalOdds(13, 8)),
    (0.325, FractionalOdds(7, 4)),
    (0.31, FractionalOdds(15, 8)),
    (0.30, FractionalOdds(2, 1)),
    (0.2875, FractionalOdds(21, 10)),
    (0.275, FractionalOdds(11, 5)),
    (0.265, FractionalOdds(9, 4)),
    (0.2575, FractionalOdds(12, 5)),
    (0.245, FractionalOdds(5, 2)),
    (0.23, FractionalOdds(11, 4)),
    (0.215, FractionalOdds(3, 1)),
    (0.2, FractionalOdds(13, 4)),
    (0.185, FractionalOdds(7, 2)),
    (0.175, FractionalOdds(15, 4)),
    (0.165, FractionalOdds(4, 1)),
    (0.155, FractionalOdds(17, 4)),
    (0.145, FractionalOdds(9, 2)),
    (0.1375, FractionalOdds(19, 4)),
    (0.13, FractionalOdds(5, 1)),
    (0.12, FractionalOdds(11, 2)),
    (0.105, FractionalOdds(6, 1)),
    (0.095, FractionalOdds(13, 2)),
    (0.085, FractionalOdds(7, 1)),
    (0.075, FractionalOdds(8, 1)),
    (0.065, FractionalOdds(9, 1)),
    (0.055, FractionalOdds(10, 1)),
    (0.045, FractionalOdds(12, 1)),
    (0.035, FractionalOdds(16, 1)),
    (0.025, FractionalOdds(20, 1)),
    (0.015, FractionalOdds(33, 1)),
    (0.005, FractionalOdds(50, 1)),
    (0.002, FractionalOdds(66, 1)),
    (0.001, FractionalOdds(100, 1)),
)
