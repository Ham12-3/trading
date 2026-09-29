"""NYSE trading calendar (holidays, early closes) backed by pandas_market_calendars."""

from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache

import pandas as pd
import pandas_market_calendars as mcal

# Schedule is materialised once for a wide window; lookups outside it are an error, not a guess.
_CALENDAR_START = date(2000, 1, 1)
_CALENDAR_END = date(2035, 12, 31)


@dataclass(frozen=True)
class Session:
    """One trading session. Times are timezone-aware UTC."""

    day: date
    open: datetime
    close: datetime


class TradingCalendar:
    """Exchange calendar with trading-day arithmetic. Default exchange: XNYS (NYSE)."""

    def __init__(self, exchange: str = "XNYS") -> None:
        self.exchange = exchange
        schedule = mcal.get_calendar(exchange).schedule(
            start_date=_CALENDAR_START.isoformat(), end_date=_CALENDAR_END.isoformat()
        )
        self._sessions: dict[date, Session] = {}
        for label, row in schedule.iterrows():
            day = pd.Timestamp(label).date()
            self._sessions[day] = Session(
                day=day,
                open=pd.Timestamp(row["market_open"]).to_pydatetime(),
                close=pd.Timestamp(row["market_close"]).to_pydatetime(),
            )
        self._days: list[date] = sorted(self._sessions)

    def _check_range(self, d: date) -> None:
        if not _CALENDAR_START <= d <= _CALENDAR_END:
            raise ValueError(f"{d} is outside the loaded calendar range")

    def is_trading_day(self, d: date) -> bool:
        """True if the exchange holds a session on ``d``."""
        self._check_range(d)
        return d in self._sessions

    def session(self, d: date) -> Session:
        """Session for trading day ``d``; raises ``ValueError`` on a non-trading day."""
        if not self.is_trading_day(d):
            raise ValueError(f"{d} is not a {self.exchange} trading day")
        return self._sessions[d]

    def next_trading_day(self, d: date) -> date:
        """First trading day strictly after ``d``."""
        nxt = d + timedelta(days=1)
        while not self.is_trading_day(nxt):
            nxt += timedelta(days=1)
        return nxt

    def previous_trading_day(self, d: date) -> date:
        """Last trading day strictly before ``d``."""
        prev = d - timedelta(days=1)
        while not self.is_trading_day(prev):
            prev -= timedelta(days=1)
        return prev

    def add_trading_days(self, d: date, n: int) -> date:
        """Trading day ``n`` sessions after trading day ``d`` (``n`` >= 0)."""
        if n < 0:
            raise ValueError("n must be non-negative")
        if not self.is_trading_day(d):
            raise ValueError(f"{d} is not a {self.exchange} trading day")
        i = bisect_left(self._days, d) + n
        if i >= len(self._days):
            raise ValueError("result is outside the loaded calendar range")
        return self._days[i]

    def trading_days(self, start: date, end: date) -> list[date]:
        """Trading days in the closed interval [start, end]."""
        return [d for d in self._days if start <= d <= end]


@lru_cache
def get_calendar(exchange: str = "XNYS") -> TradingCalendar:
    """Process-wide cached calendar (building the schedule takes ~1s)."""
    return TradingCalendar(exchange)
