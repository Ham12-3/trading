"""Event study: mean abnormal return, t-stat and count per signal bucket and window (PRD 10.1).

t-stats assume independent events. Earnings cluster in a few weeks per quarter, so events on the
same days are correlated and these t-stats overstate significance; this is listed as a
limitation rather than corrected in v1.
"""

import math
from dataclasses import asdict, dataclass

import pandas as pd

from newsalpha.backtest.events import WINDOWS


@dataclass(frozen=True)
class BucketStat:
    grouping: str
    bucket: str
    window: int
    n: int
    mean_ar: float | None
    std_ar: float | None
    t_stat: float | None


def mean_t(values: pd.Series) -> tuple[int, float | None, float | None, float | None]:
    """(n, mean, sample std, t-stat of the mean vs zero). t needs n >= 2 and non-zero std."""
    clean = values.dropna().astype(float)
    n = len(clean)
    if n == 0:
        return 0, None, None, None
    mean = float(clean.mean())
    if n < 2:
        return n, mean, None, None
    sd = float(clean.std(ddof=1))
    t = mean / (sd / math.sqrt(n)) if sd > 0 else None
    return n, mean, sd, t


def event_study(frame: pd.DataFrame, groupings: dict[str, str]) -> list[BucketStat]:
    """Stats for every (grouping, bucket, window).

    ``frame`` has one row per event with columns ``ar_1``/``ar_3``/``ar_5`` and one column per
    grouping (its bucket label). ``groupings`` maps a display name to that column.
    """
    out: list[BucketStat] = []
    for name, column in groupings.items():
        for bucket, rows in frame.dropna(subset=[column]).groupby(column, sort=True):
            for k in WINDOWS:
                n, mean, sd, t = mean_t(rows[f"ar_{k}"])
                out.append(BucketStat(name, str(bucket), k, n, mean, sd, t))
    return out


def as_records(stats: list[BucketStat]) -> list[dict[str, object]]:
    return [asdict(s) for s in stats]
