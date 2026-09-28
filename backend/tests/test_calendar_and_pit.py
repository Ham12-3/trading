"""Trading calendar arithmetic and the point-in-time price view (incl. the lookahead trap)."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from newsalpha.core.calendar import TradingCalendar, get_calendar
from newsalpha.core.pit import LookaheadError, PointInTimePrices
from newsalpha.core.time_rules import entry_time, event_day

ET = ZoneInfo("America/New_York")


@pytest.fixture(scope="module")
def cal() -> TradingCalendar:
    return get_calendar()


def test_holidays_and_early_closes(cal: TradingCalendar) -> None:
    assert not cal.is_trading_day(date(2024, 12, 25))
    assert not cal.is_trading_day(date(2024, 1, 27))  # Saturday
    early = cal.session(date(2024, 11, 29))
    assert early.close.astimezone(ET).hour == 13


def test_add_trading_days_skips_weekend_and_holiday(cal: TradingCalendar) -> None:
    assert cal.add_trading_days(date(2024, 7, 3), 1) == date(2024, 7, 5)
    assert cal.add_trading_days(date(2024, 7, 3), 3) == date(2024, 7, 9)
    assert cal.add_trading_days(date(2024, 7, 3), 0) == date(2024, 7, 3)


def _bars(days: list[date], adj_close: list[float]) -> pd.DataFrame:
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days], name="date")
    return pd.DataFrame(
        {"adj_open": [c - 0.5 for c in adj_close], "adj_close": adj_close}, index=idx
    )


def test_lookahead_trap(cal: TradingCalendar) -> None:
    """Inject an absurd future price and assert nothing computed at entry can see it."""
    accepted = datetime(2024, 1, 23, 16, 5, tzinfo=ET)  # after close -> t0 = 2024-01-24
    t0 = event_day(accepted, cal)
    entry = entry_time(t0, cal)
    days = [date(2024, 1, 19), date(2024, 1, 22), date(2024, 1, 23), t0, date(2024, 1, 25)]
    trap = 1_000_000.0
    prices = PointInTimePrices(_bars(days, [100, 101, 102, trap, trap]), cal)

    visible = prices.history(entry)
    assert list(pd.DatetimeIndex(visible.index).date) == [
        date(2024, 1, 19),
        date(2024, 1, 22),
        date(2024, 1, 23),
    ]
    assert trap not in visible["adj_close"].to_numpy()

    # The t0 open is the entry price and is known exactly at entry...
    assert prices.adj_open(t0, entry) == trap - 0.5
    # ...but the t0 close and anything later are not.
    with pytest.raises(LookaheadError):
        prices.adj_close(t0, entry)
    with pytest.raises(LookaheadError):
        prices.adj_open(date(2024, 1, 25), entry)


def test_open_is_not_known_one_second_early(cal: TradingCalendar) -> None:
    t0 = date(2024, 1, 24)
    prices = PointInTimePrices(_bars([t0], [50.0]), cal)
    just_before = entry_time(t0, cal) - timedelta(seconds=1)
    with pytest.raises(LookaheadError):
        prices.adj_open(t0, just_before)
