import math
from typing import NamedTuple

from loguru import logger


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
    n_simulations: int,
    k: float = 2.0,
    flat_margin: float = 0.07,
    margin_buffer: float = 0.01,
    ladder: list[FractionalOdds] | None = None,
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
    if not probabilities:
        raise ValueError("probabilities list is empty")
    if any(p < 0 or p > 1 for p in probabilities):
        raise ValueError("all probabilities must be between 0 and 1")
    if abs(sum(probabilities) - 1.0) > 0.01:
        raise ValueError(
            f"probabilities should sum to 1.0, got {sum(probabilities):.4f}"
        )

    if n_simulations < 1:
        raise ValueError("n_simulations must be >= 1")
    if flat_margin < 0:
        raise ValueError("flat_margin must be >= 0")

    _ladder = ladder or BOOKMAKER_LADDER
    min_odds, max_odds = _ladder[0], _ladder[-1]
    min_dec = min_odds.decimal
    max_dec = max_odds.decimal

    # Pre-compute decimal values for the ladder once, sorted ascending
    ladder_dec = [(f.decimal, f) for f in _ladder]
    ladder_dec.sort()

    result = []
    for p in probabilities:
        if not (0 < p < 1):
            # Don't offer odds for impossible or certain outcomes; return None to indicate no bet offered
            logger.warning(
                f"Probability {p:.4f} is out of bounds (0,1). No odds will be offered for this runner."
            )
            result.append(None)
            continue

        # Standard error of a proportion from MC simulation
        se = math.sqrt(p * (1 - p) / n_simulations)

        # SE margin: covers sampling noise (proportional to uncertainty in estimate)
        # Flat margin: covers model error (applied equally to all runners)
        adjusted_p = (p + k * se) * (1 + flat_margin) + margin_buffer

        # Convert to decimal odds and clamp to [min_odds, max_odds]
        raw_dec = 1.0 / adjusted_p
        clamped_dec = max(min_dec, min(max_dec, raw_dec))

        # Round down to the nearest rung on the ladder
        rungs_below = [(d, f) for d, f in ladder_dec if d <= clamped_dec]
        if rungs_below:
            _, best_frac = max(rungs_below)  # largest decimal that is still <= clamped
        else:
            best_frac = min_odds  # below the bottom of the ladder

        result.append(best_frac)

    return result


# ---------------------------------------------------------------------------
# Standard fractional bookmaker odds ladder
# ---------------------------------------------------------------------------
BOOKMAKER_LADDER: list[FractionalOdds] = [
    FractionalOdds(1, 500),
    FractionalOdds(1, 200),
    FractionalOdds(1, 100),
    FractionalOdds(1, 50),
    FractionalOdds(1, 20),
    FractionalOdds(1, 14),
    FractionalOdds(1, 10),
    FractionalOdds(1, 8),
    FractionalOdds(1, 7),
    FractionalOdds(1, 6),
    FractionalOdds(1, 5),
    FractionalOdds(2, 9),
    FractionalOdds(1, 4),
    FractionalOdds(2, 7),
    FractionalOdds(3, 10),
    FractionalOdds(1, 3),
    FractionalOdds(4, 11),
    FractionalOdds(2, 5),
    FractionalOdds(4, 9),
    FractionalOdds(1, 2),
    FractionalOdds(8, 15),
    FractionalOdds(4, 7),
    FractionalOdds(8, 13),
    FractionalOdds(4, 6),
    FractionalOdds(8, 11),
    FractionalOdds(4, 5),
    FractionalOdds(5, 6),
    FractionalOdds(10, 11),
    FractionalOdds(1, 1),
    FractionalOdds(21, 20),
    FractionalOdds(11, 10),
    FractionalOdds(23, 20),
    FractionalOdds(6, 5),
    FractionalOdds(5, 4),
    FractionalOdds(11, 8),
    FractionalOdds(7, 5),
    FractionalOdds(6, 4),
    FractionalOdds(8, 5),
    FractionalOdds(13, 8),
    FractionalOdds(7, 4),
    FractionalOdds(9, 5),
    FractionalOdds(15, 8),
    FractionalOdds(2, 1),
    FractionalOdds(11, 5),
    FractionalOdds(9, 4),
    FractionalOdds(12, 5),
    FractionalOdds(5, 2),
    FractionalOdds(13, 5),
    FractionalOdds(11, 4),
    FractionalOdds(3, 1),
    FractionalOdds(16, 5),
    FractionalOdds(10, 3),
    FractionalOdds(7, 2),
    FractionalOdds(4, 1),
    FractionalOdds(9, 2),
    FractionalOdds(5, 1),
    FractionalOdds(11, 2),
    FractionalOdds(6, 1),
    FractionalOdds(13, 2),
    FractionalOdds(7, 1),
    FractionalOdds(15, 2),
    FractionalOdds(8, 1),
    FractionalOdds(9, 1),
    FractionalOdds(10, 1),
    FractionalOdds(11, 1),
    FractionalOdds(12, 1),
    FractionalOdds(13, 1),
    FractionalOdds(14, 1),
    FractionalOdds(15, 1),
    FractionalOdds(16, 1),
    FractionalOdds(18, 1),
    FractionalOdds(20, 1),
    FractionalOdds(25, 1),
    FractionalOdds(33, 1),
    FractionalOdds(50, 1),
    FractionalOdds(66, 1),
    FractionalOdds(100, 1),
]
