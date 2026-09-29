"""Small, dependency-free statistics helpers."""


def percentile(values: list[float] | list[int], q: float) -> float:
    """Nearest-rank percentile (q in 0..100); 0.0 for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, round(q / 100 * len(ordered)))
    return float(ordered[min(rank, len(ordered)) - 1])
