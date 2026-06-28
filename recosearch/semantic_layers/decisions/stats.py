from __future__ import annotations

import math

CONFIDENCE_METHODS = frozenset({"wilson"})


def wilson_interval(successes: int, total: int, *, z: float = 1.96) -> tuple[float, float, float]:
    """Wilson score interval for a binomial proportion."""
    if total <= 0:
        return 0.0, 0.0, 0.0
    p = successes / total
    z2 = z * z
    denom = 1.0 + z2 / total
    center = (p + z2 / (2.0 * total)) / denom
    margin = (z / denom) * math.sqrt((p * (1.0 - p) / total) + (z2 / (4.0 * total * total)))
    return p, max(0.0, center - margin), min(1.0, center + margin)


def match_rate_interval(
    matches: int,
    total: int,
    *,
    method: str = "wilson",
) -> tuple[float, float, float, float]:
    """Return match_rate, ci_low, ci_high, miss_rate for realized calibration outcomes."""
    if method not in CONFIDENCE_METHODS:
        raise ValueError(f"unknown confidence method: {method}")
    match_rate, ci_low, ci_high = wilson_interval(matches, total)
    miss_rate = 1.0 - match_rate if total > 0 else 0.0
    return match_rate, ci_low, ci_high, miss_rate


def miss_rate_ci_low(matches: int, total: int, *, method: str = "wilson") -> float:
    """Lower bound of miss-rate Wilson interval (failures = total - matches)."""
    if method not in CONFIDENCE_METHODS:
        raise ValueError(f"unknown confidence method: {method}")
    if total <= 0:
        return 0.0
    misses = total - matches
    _, miss_ci_low, _ = wilson_interval(misses, total)
    return miss_ci_low
