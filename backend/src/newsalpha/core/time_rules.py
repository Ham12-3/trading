"""Point-in-time event rules (PRD section 7).

An announcement's EDGAR acceptance timestamp decides its event day t0:

* accepted before the open (09:30 ET) on a trading day -> t0 is that day;
* accepted during market hours, after the close, or on a non-trading day -> t0 is the next
  trading day.

Entry is always at t0's open. Nothing timestamped after the entry time may feed a signal.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from newsalpha.core.calendar import TradingCalendar

EASTERN = ZoneInfo("America/New_York")


def _require_aware(ts: datetime) -> None:
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware; naive times are ambiguous")


def event_day(accepted_at: datetime, calendar: TradingCalendar) -> date:
    """Return t0 for an announcement accepted at ``accepted_at`` (timezone-aware)."""
    _require_aware(accepted_at)
    local_day = accepted_at.astimezone(EASTERN).date()
    if calendar.is_trading_day(local_day) and accepted_at < calendar.session(local_day).open:
        return local_day
    return calendar.next_trading_day(local_day)


def entry_time(t0: date, calendar: TradingCalendar) -> datetime:
    """Entry timestamp (UTC) for event day ``t0``: that session's open."""
    return calendar.session(t0).open


def is_known_at(data_timestamp: datetime, as_of: datetime) -> bool:
    """True if data stamped ``data_timestamp`` was available at ``as_of`` (inclusive)."""
    _require_aware(data_timestamp)
    _require_aware(as_of)
    return data_timestamp <= as_of
