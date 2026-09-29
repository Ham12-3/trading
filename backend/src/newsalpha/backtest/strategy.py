"""Turn events into trade decisions: the LLM composite and two non-LLM baselines.

Every input here is known at the t0 open: LLM labels come from text accepted before entry, and
the opening gap uses the t0 open and the previous close only.
"""

import numpy as np
import pandas as pd

from newsalpha.backtest.config import Weights

GUIDANCE_SCORE = {
    "raised": 1.0,
    "lowered": -1.0,
    "withdrawn": -1.0,
    "maintained": 0.0,
    "not_mentioned": 0.0,
}
EXPECTATION_SCORE = {"beat": 1.0, "miss": -1.0, "inline": 0.0, "unknown": 0.0}


def composite_score(frame: pd.DataFrame, weights: Weights, tone_center: float) -> pd.Series:
    """score = w_g*guidance + w_t*(tone - center) + w_r*revenue + w_e*eps (NaN if no signal)."""
    return (
        weights.guidance * frame["guidance_direction"].map(GUIDANCE_SCORE)
        + weights.tone * (frame["management_tone"] - tone_center)
        + weights.revenue * frame["revenue_vs_expectation"].map(EXPECTATION_SCORE)
        + weights.eps * frame["eps_vs_expectation"].map(EXPECTATION_SCORE)
    )


def threshold_sides(score: pd.Series, long_above: float, short_below: float) -> pd.Series:
    """+1 long, -1 short, 0 flat (NaN scores are flat)."""
    side = np.where(score > long_above, 1, np.where(score < short_below, -1, 0))
    return pd.Series(side, index=score.index, dtype=int)


def beat_miss_sides(frame: pd.DataFrame) -> pd.Series:
    """PRD's naive rule: long if revenue or EPS beat (and nothing missed), short if any miss."""
    rev, eps = frame["revenue_vs_expectation"], frame["eps_vs_expectation"]
    miss = (rev == "miss") | (eps == "miss")
    beat = ((rev == "beat") | (eps == "beat")) & ~miss
    return pd.Series(np.where(beat, 1, np.where(miss, -1, 0)), index=frame.index, dtype=int)


def gap_sides(frame: pd.DataFrame, threshold: float) -> pd.Series:
    """Follow the market's first reaction: sign of the abnormal opening gap beyond ``threshold``."""
    gap = frame["gap_abnormal"]
    side = np.where(gap > threshold, 1, np.where(gap < -threshold, -1, 0))
    return pd.Series(side, index=frame.index, dtype=int)
