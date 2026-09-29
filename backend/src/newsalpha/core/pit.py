"""Point-in-time view over daily bars.

A daily bar for day ``d`` has two availability times: its open is known at the session open,
and its high/low/close/volume only at the session close. Code that computes signals must read
prices through this view so a future bar cannot leak in.
"""

from datetime import date, datetime

import pandas as pd

from newsalpha.core.calendar import TradingCalendar
from newsalpha.core.time_rules import is_known_at

BAR_COLUMNS = ("open", "high", "low", "close", "adj_open", "adj_close", "volume")


class LookaheadError(RuntimeError):
    """Raised when code asks for a price that was not yet known at the given time."""


class PointInTimePrices:
    """Daily bars for one symbol, indexed by trading date, queried as of a timestamp."""

    def __init__(self, bars: pd.DataFrame, calendar: TradingCalendar) -> None:
        missing = [c for c in ("adj_open", "adj_close") if c not in bars.columns]
        if missing:
            raise ValueError(f"bars are missing columns: {missing}")
        self._bars = bars.sort_index()
        self._calendar = calendar

    def history(self, as_of: datetime) -> pd.DataFrame:
        """Complete bars whose session closed at or before ``as_of``."""
        keep = [
            d
            for d in self._bars.index
            if is_known_at(self._calendar.session(_as_date(d)).close, as_of)
        ]
        return self._bars.loc[keep]

    def adj_open(self, day: date, as_of: datetime) -> float:
        """Adjusted open for ``day``; raises ``LookaheadError`` if asked before that open."""
        opened_at = self._calendar.session(day).open
        if not is_known_at(opened_at, as_of):
            raise LookaheadError(f"open of {day} is not known at {as_of.isoformat()}")
        return float(self._bars.at[pd.Timestamp(day), "adj_open"])  # type: ignore[arg-type]

    def adj_close(self, day: date, as_of: datetime) -> float:
        """Adjusted close for ``day``; raises ``LookaheadError`` if asked before that close."""
        closed_at = self._calendar.session(day).close
        if not is_known_at(closed_at, as_of):
            raise LookaheadError(f"close of {day} is not known at {as_of.isoformat()}")
        return float(self._bars.at[pd.Timestamp(day), "adj_close"])  # type: ignore[arg-type]


def _as_date(label: object) -> date:
    return pd.Timestamp(str(label)).date()
