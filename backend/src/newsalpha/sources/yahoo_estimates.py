"""Analyst EPS consensus vs reported EPS per quarter, from Yahoo Finance via ``yfinance``.

This is a *numeric*, non-LLM input: it lets the backtest ask whether reading the release text adds
anything beyond the headline EPS surprise.

Caveats (reported with results): the consensus is Yahoo's snapshot around the report date, not a
timestamped point-in-time series; "reported EPS" is on the analysts' (usually adjusted) basis;
yfinance is an unofficial interface suitable for personal research, not a licensed feed.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
import yfinance as yf

from newsalpha.sources.base import SourceError
from newsalpha.sources.yahoo import yahoo_symbol

log = logging.getLogger(__name__)
HISTORY_LIMIT = 40  # quarters requested; Yahoo returns what it has


@dataclass(frozen=True)
class EpsQuarter:
    earnings_at: datetime  # Yahoo's report time, timezone-aware
    eps_estimate: float | None
    eps_reported: float | None


def surprise_pct(reported: float | None, estimate: float | None) -> float | None:
    """(reported - estimate) / |estimate|; None when either is missing or the estimate is ~0."""
    if reported is None or estimate is None or abs(estimate) < 1e-9:
        return None
    return (reported - estimate) / abs(estimate)


def normalise_earnings_dates(raw: pd.DataFrame, symbol: str) -> list[EpsQuarter]:
    """Parse ``Ticker.get_earnings_dates`` output; rows without either figure keep None."""
    missing = [c for c in ("EPS Estimate", "Reported EPS") if c not in raw.columns]
    if missing:
        raise SourceError(f"{symbol}: earnings data is missing columns {missing}")
    out = []
    for ts, est, rep in zip(
        raw.index, raw["EPS Estimate"].tolist(), raw["Reported EPS"].tolist(), strict=True
    ):
        stamp = pd.Timestamp(ts)
        if stamp.tzinfo is None:
            raise SourceError(f"{symbol}: earnings timestamp without a timezone")
        out.append(
            EpsQuarter(
                earnings_at=stamp.to_pydatetime(),
                eps_estimate=None if pd.isna(est) else float(est),
                eps_reported=None if pd.isna(rep) else float(rep),
            )
        )
    return out


class YahooEstimatesSource:
    """Per-quarter EPS consensus and actuals, with pacing and retries like the price source."""

    name = "yfinance"

    def __init__(
        self, *, pause_seconds: float = 1.0, max_retries: int = 3, backoff_seconds: float = 10.0
    ) -> None:
        self._pause = pause_seconds
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        yf.config.debug.hide_exceptions = False

    def _download(self, ysym: str) -> pd.DataFrame:
        raw: pd.DataFrame | None = yf.Ticker(ysym).get_earnings_dates(limit=HISTORY_LIMIT)
        if raw is None or raw.empty:
            raise SourceError(f"yfinance returned no earnings dates for {ysym}")
        return raw

    def fetch(self, symbol: str) -> list[EpsQuarter]:
        ysym = yahoo_symbol(symbol)
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            time.sleep(self._pause if attempt == 0 else self._backoff * 2 ** (attempt - 1))
            try:
                return normalise_earnings_dates(self._download(ysym), ysym)
            except Exception as exc:  # yfinance raises a variety of types
                last_error = exc
                log.warning(
                    "yfinance earnings attempt %d failed for %s: %s", attempt + 1, ysym, exc
                )
        raise SourceError(
            f"yfinance earnings failed for {ysym} after {self._max_retries + 1} attempts: "
            f"{last_error}"
        ) from last_error
