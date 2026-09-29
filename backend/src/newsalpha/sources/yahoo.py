"""Daily prices from Yahoo Finance via ``yfinance`` (swap for a paid ``PriceSource`` later).

Raw OHLC is stored alongside ``adj_close``; ``adj_open`` is derived with the same split/dividend
factor (adj_close / close) so returns measured from the entry open are consistent with
adjusted closes.
"""

import logging
import time
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from newsalpha.sources.base import SourceError

log = logging.getLogger(__name__)

COLUMNS = ["open", "high", "low", "close", "adj_close", "adj_open", "volume"]


def yahoo_symbol(ticker: str) -> str:
    """Yahoo spells share classes with a dash (BRK.B -> BRK-B)."""
    return ticker.replace(".", "-").upper()


def normalise_bars(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Convert a yfinance frame (Open/High/Low/Close/Adj Close/Volume) to our bar schema."""
    required = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    missing = [c for c in required if c not in raw.columns]
    if missing:
        raise SourceError(f"{symbol}: price data is missing columns {missing}")
    bars = raw[required].rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
        }
    )
    bars = bars.dropna(subset=["open", "close", "adj_close"])
    bars["adj_open"] = bars["open"] * (bars["adj_close"] / bars["close"])
    index = pd.DatetimeIndex(bars.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    bars.index = index.normalize()
    bars.index.name = "date"
    return bars[COLUMNS]


class YahooPriceSource:
    """``PriceSource`` backed by yfinance.

    Yahoo throttles bursts and then reports every symbol as "possibly delisted", so calls are
    spaced out and retried with exponential backoff before a failure is reported.
    """

    name = "yfinance"

    def __init__(
        self, *, pause_seconds: float = 1.0, max_retries: int = 3, backoff_seconds: float = 10.0
    ) -> None:
        self._pause = pause_seconds
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        yf.config.debug.hide_exceptions = False  # raise instead of printing and returning empty

    def _download(self, ysym: str, start: date, end: date) -> pd.DataFrame:
        raw: pd.DataFrame | None = yf.Ticker(ysym).history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),  # yfinance end is exclusive
            interval="1d",
            auto_adjust=False,
            actions=False,
        )
        if raw is None or raw.empty:
            raise SourceError(f"yfinance returned no rows for {ysym} {start}..{end}")
        return raw

    def fetch_daily(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        ysym = yahoo_symbol(symbol)
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            time.sleep(self._pause if attempt == 0 else self._backoff * 2 ** (attempt - 1))
            try:
                return normalise_bars(self._download(ysym, start, end), ysym)
            except Exception as exc:  # yfinance raises a variety of types
                last_error = exc
                log.warning("yfinance attempt %d failed for %s: %s", attempt + 1, ysym, exc)
        raise SourceError(
            f"yfinance failed for {ysym} after {self._max_retries + 1} attempts: {last_error}"
        ) from last_error
