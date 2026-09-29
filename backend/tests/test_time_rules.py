"""PRD section 7: event day t0 and entry time from the acceptance timestamp."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from newsalpha.core.calendar import TradingCalendar, get_calendar
from newsalpha.core.time_rules import entry_time, event_day, is_known_at

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


@pytest.fixture(scope="module")
def cal() -> TradingCalendar:
    return get_calendar()


def et(y: int, m: int, d: int, hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=ET)


@pytest.mark.parametrize(
    ("accepted", "expected_t0", "case"),
    [
        # Tue 2024-01-23 is a normal trading day.
        (et(2024, 1, 23, 6, 45), date(2024, 1, 23), "pre-market -> same day"),
        (et(2024, 1, 23, 0, 0), date(2024, 1, 23), "just after midnight -> same day"),
        (et(2024, 1, 23, 9, 29, 59), date(2024, 1, 23), "one second before open -> same day"),
        (et(2024, 1, 23, 9, 30, 0), date(2024, 1, 24), "exactly at open -> next day"),
        (et(2024, 1, 23, 12, 0), date(2024, 1, 24), "intraday -> next day"),
        (et(2024, 1, 23, 16, 5), date(2024, 1, 24), "after close -> next day"),
        (et(2024, 1, 23, 23, 59), date(2024, 1, 24), "late evening -> next day"),
        # Weekend: Fri 2024-01-26 after close, Sat, Sun -> Mon 2024-01-29.
        (et(2024, 1, 26, 16, 30), date(2024, 1, 29), "Friday after close -> Monday"),
        (et(2024, 1, 27, 8, 0), date(2024, 1, 29), "Saturday morning -> Monday"),
        (et(2024, 1, 28, 20, 0), date(2024, 1, 29), "Sunday evening -> Monday"),
        # Holiday: Thu 2024-07-04 closed; Wed 2024-07-03 is an early close (13:00 ET).
        (et(2024, 7, 4, 7, 0), date(2024, 7, 5), "holiday pre-market -> next session"),
        (et(2024, 7, 3, 13, 30), date(2024, 7, 5), "after early close, skips holiday"),
        (et(2024, 7, 3, 8, 0), date(2024, 7, 3), "early-close day pre-market -> same day"),
        # Good Friday 2024-03-29 closed; announcement Thursday after close -> Monday 04-01.
        (et(2024, 3, 28, 16, 10), date(2024, 4, 1), "before Good Friday -> Monday"),
        # Thanksgiving 2024-11-28 closed, 11-29 early close.
        (et(2024, 11, 27, 17, 0), date(2024, 11, 29), "Wed before Thanksgiving -> Fri"),
    ],
)
def test_event_day(cal: TradingCalendar, accepted: datetime, expected_t0: date, case: str) -> None:
    assert event_day(accepted, cal) == expected_t0, case


def test_event_day_is_independent_of_input_timezone(cal: TradingCalendar) -> None:
    # 2024-01-23 14:29 UTC == 09:29 ET (EST, UTC-5): still pre-market.
    assert event_day(datetime(2024, 1, 23, 14, 29, tzinfo=UTC), cal) == date(2024, 1, 23)
    # 2024-07-02 13:29 UTC == 09:29 ET (EDT, UTC-4): pre-market across DST.
    assert event_day(datetime(2024, 7, 2, 13, 29, tzinfo=UTC), cal) == date(2024, 7, 2)
    assert event_day(datetime(2024, 7, 2, 13, 30, tzinfo=UTC), cal) == date(2024, 7, 3)


def test_utc_date_differs_from_eastern_date(cal: TradingCalendar) -> None:
    # 2024-01-24 02:00 UTC is still 2024-01-23 21:00 ET: after Tuesday's close -> Wednesday.
    assert event_day(datetime(2024, 1, 24, 2, 0, tzinfo=UTC), cal) == date(2024, 1, 24)


def test_naive_timestamp_is_rejected(cal: TradingCalendar) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        event_day(datetime(2024, 1, 23, 8, 0), cal)  # noqa: DTZ001


def test_entry_time_is_session_open(cal: TradingCalendar) -> None:
    assert entry_time(date(2024, 1, 23), cal) == et(2024, 1, 23, 9, 30)
    assert entry_time(date(2024, 7, 5), cal) == et(2024, 7, 5, 9, 30)


def test_entry_time_rejects_non_trading_day(cal: TradingCalendar) -> None:
    with pytest.raises(ValueError, match="not a XNYS trading day"):
        entry_time(date(2024, 7, 4), cal)


def test_announcement_is_known_before_entry(cal: TradingCalendar) -> None:
    """Whatever the case, the announcement itself is always known by the entry time."""
    for accepted in [et(2024, 1, 23, 6, 45), et(2024, 1, 23, 16, 5), et(2024, 7, 3, 13, 30)]:
        assert is_known_at(accepted, entry_time(event_day(accepted, cal), cal))
