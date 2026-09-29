"""Event construction: t0, entry price, opening gap and abnormal returns per announcement.

What is known at entry (t0 open) and what is an outcome are kept apart:

* the opening gap (t0 open vs the previous close) is read through ``PointInTimePrices`` as of the
  entry time, so it cannot touch the t0 close or anything later;
* window returns are *outcomes* (entry open to the close of t0+k) and are never used as inputs.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from newsalpha.core.calendar import TradingCalendar
from newsalpha.core.pit import PointInTimePrices
from newsalpha.core.time_rules import entry_time, event_day
from newsalpha.db.models import Announcement, Company, Event, PriceDaily

log = logging.getLogger(__name__)

WINDOWS = (1, 3, 5)  # [t0, t0+k]: entry at the t0 open, exit at the close of trading day t0+k


@dataclass
class EventRecord:
    t0: date
    entry_time: datetime
    entry_price: float | None = None  # stock adjusted open at t0
    bench_entry_price: float | None = None
    gap_abnormal: float | None = None  # (stock open/prev close - 1) - (bench open/prev close - 1)
    ret: dict[int, float | None] = field(default_factory=dict)
    bench_ret: dict[int, float | None] = field(default_factory=dict)
    ar: dict[int, float | None] = field(default_factory=dict)


def bar_value(bars: pd.DataFrame, ts: pd.Timestamp, column: str) -> float:
    """One adjusted price from a bar frame indexed by date (raises KeyError if absent)."""
    return float(bars[column].to_numpy(dtype=float)[bars.index.get_loc(ts)])


def _window_return(bars: pd.DataFrame, entry_price: float, exit_day: date) -> float | None:
    ts = pd.Timestamp(exit_day)
    if ts not in bars.index:
        return None
    return bar_value(bars, ts, "adj_close") / entry_price - 1.0


def _gap(prices: PointInTimePrices, prev: date, t0: date, at: datetime) -> float | None:
    try:
        return prices.adj_open(t0, at) / prices.adj_close(prev, at) - 1.0
    except KeyError:
        return None


def compute_event(
    accepted_at: datetime,
    stock: pd.DataFrame,
    bench: pd.DataFrame,
    calendar: TradingCalendar,
    windows: tuple[int, ...] = WINDOWS,
) -> EventRecord:
    """Build one event. Missing prices leave fields as ``None``; nothing is filled in or guessed."""
    t0 = event_day(accepted_at, calendar)
    entry = entry_time(t0, calendar)
    rec = EventRecord(t0=t0, entry_time=entry)
    t0_ts = pd.Timestamp(t0)
    if t0_ts not in stock.index or t0_ts not in bench.index:
        return rec

    stock_pit = PointInTimePrices(stock, calendar)
    bench_pit = PointInTimePrices(bench, calendar)
    rec.entry_price = stock_pit.adj_open(t0, entry)
    rec.bench_entry_price = bench_pit.adj_open(t0, entry)
    prev = calendar.previous_trading_day(t0)
    s_gap, b_gap = _gap(stock_pit, prev, t0, entry), _gap(bench_pit, prev, t0, entry)
    if s_gap is not None and b_gap is not None:
        rec.gap_abnormal = s_gap - b_gap

    for k in windows:
        exit_day = calendar.add_trading_days(t0, k)
        r = _window_return(stock, rec.entry_price, exit_day)
        b = _window_return(bench, rec.bench_entry_price, exit_day)
        rec.ret[k], rec.bench_ret[k] = r, b
        rec.ar[k] = r - b if r is not None and b is not None else None
    return rec


def load_price_panel(session: Session, symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Adjusted daily bars per symbol, indexed by date (Timestamp)."""
    rows = session.execute(
        select(PriceDaily.symbol, PriceDaily.date, PriceDaily.adj_open, PriceDaily.adj_close).where(
            PriceDaily.symbol.in_(symbols)
        )
    ).all()
    frame = pd.DataFrame(rows, columns=["symbol", "date", "adj_open", "adj_close"])
    frame["date"] = pd.to_datetime(frame["date"])
    return {
        str(sym): grp.set_index("date")[["adj_open", "adj_close"]].sort_index()
        for sym, grp in frame.groupby("symbol")
    }


@dataclass
class EventBuildReport:
    built: int = 0
    no_prices: int = 0
    incomplete_windows: int = 0


def build_events(
    session: Session, calendar: TradingCalendar, benchmark: str = "SPY"
) -> EventBuildReport:
    """(Re)build the ``events`` table from announcements and prices. Idempotent."""
    anns = session.execute(
        select(Announcement.id, Announcement.accepted_at, Company.ticker).join(
            Company, Company.id == Announcement.company_id
        )
    ).all()
    panel = load_price_panel(session, sorted({t for _, _, t in anns} | {benchmark}))
    if benchmark not in panel:
        raise RuntimeError(f"no prices for benchmark {benchmark}; run `ingest prices` first")
    report = EventBuildReport()
    rows = []
    for ann_id, accepted_at, ticker in anns:
        stock = panel.get(ticker)
        if stock is None:
            report.no_prices += 1
            continue
        rec = compute_event(accepted_at, stock, panel[benchmark], calendar)
        if rec.entry_price is None:
            report.no_prices += 1
            log.warning("%s announcement %d: no t0 price for %s", ticker, ann_id, rec.t0)
        elif any(v is None for v in rec.ar.values()):
            report.incomplete_windows += 1
        rows.append(
            {
                "announcement_id": ann_id,
                "t0_date": rec.t0,
                "entry_time": rec.entry_time,
                "entry_price": rec.entry_price,
                "bench_entry_price": rec.bench_entry_price,
                "gap_abnormal": rec.gap_abnormal,
                **{f"ret_{k}": rec.ret.get(k) for k in WINDOWS},
                **{f"bench_ret_{k}": rec.bench_ret.get(k) for k in WINDOWS},
                **{f"ar_{k}": rec.ar.get(k) for k in WINDOWS},
            }
        )
    if rows:
        stmt = insert(Event).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Event.announcement_id],
            set_={c: stmt.excluded[c] for c in rows[0] if c != "announcement_id"},
        )
        session.execute(stmt)
        session.commit()
    report.built = len(rows)
    return report
