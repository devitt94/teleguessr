import math


# ---------------------------------------------------------------------------
# Type alias: fractional odds are (numerator, denominator) tuples, e.g. (5, 2)
# ---------------------------------------------------------------------------
FractionalOdds = tuple[int, int]


def fractional_to_decimal(frac: FractionalOdds) -> float:
    """Convert fractional odds to decimal. e.g. (5, 2) -> 3.5, (1, 1) -> 2.0"""
    num, den = frac
    return 1.0 + num / den


def format_fractional(frac: FractionalOdds) -> str:
    """Format fractional odds as a string, e.g. (5, 2) -> '5/2'"""
    return f"{frac[0]}/{frac[1]}"


def probs_to_odds(
    probabilities: list[float],
    n_simulations: int,
    k: float = 2.0,
    flat_margin: float = 0.025,
    ladder: list[FractionalOdds] | None = None,
) -> list[FractionalOdds]:
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
        min_odds:        Floor on offered odds as fractional tuple (default 1/100).
        max_odds:        Ceiling on offered odds as fractional tuple (default 66/1).
        ladder:          Optional list of fractional odds tuples to round down to.
                         If None, rounds down to the nearest rung on BOOKMAKER_LADDER.

    Returns:
        List of fractional odds tuples (numerator, denominator),
        in the same order as the input probabilities.
    """
    if not probabilities:
        raise ValueError("probabilities list is empty")
    if any(p <= 0 or p >= 1 for p in probabilities):
        raise ValueError("all probabilities must be strictly between 0 and 1")
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
    min_dec = fractional_to_decimal(min_odds)
    max_dec = fractional_to_decimal(max_odds)

    # Pre-compute decimal values for the ladder once, sorted ascending
    ladder_dec = [(fractional_to_decimal(f), f) for f in _ladder]
    ladder_dec.sort()

    result = []
    for p in probabilities:
        # Standard error of a proportion from MC simulation
        se = math.sqrt(p * (1 - p) / n_simulations)

        # SE margin: covers sampling noise (proportional to uncertainty in estimate)
        # Flat margin: covers model error (applied equally to all runners)
        adjusted_p = (p + k * se) + flat_margin

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
    (1, 100),
    (1, 5),
    (2, 9),
    (1, 4),
    (2, 7),
    (3, 10),
    (1, 3),
    (4, 11),
    (2, 5),
    (4, 9),
    (1, 2),
    (8, 15),
    (4, 7),
    (8, 13),
    (4, 6),
    (8, 11),
    (4, 5),
    (5, 6),
    (10, 11),
    (1, 1),
    (21, 20),
    (11, 10),
    (23, 20),
    (6, 5),
    (5, 4),
    (11, 8),
    (7, 5),
    (6, 4),
    (8, 5),
    (13, 8),
    (7, 4),
    (9, 5),
    (15, 8),
    (2, 1),
    (11, 5),
    (9, 4),
    (12, 5),
    (5, 2),
    (13, 5),
    (11, 4),
    (3, 1),
    (16, 5),
    (10, 3),
    (7, 2),
    (4, 1),
    (9, 2),
    (5, 1),
    (11, 2),
    (6, 1),
    (13, 2),
    (7, 1),
    (15, 2),
    (8, 1),
    (9, 1),
    (10, 1),
    (11, 1),
    (12, 1),
    (13, 1),
    (14, 1),
    (15, 1),
    (16, 1),
    (18, 1),
    (20, 1),
    (25, 1),
    (33, 1),
    (50, 1),
    (66, 1),
    (100, 1),
]
