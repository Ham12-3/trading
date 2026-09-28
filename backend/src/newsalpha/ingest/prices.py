"""Ingest daily bars for the universe and benchmark into ``prices_daily``."""

import logging
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from newsalpha.db.models import PriceDaily
from newsalpha.sources.base import PriceSource, SourceError

log = logging.getLogger(__name__)


@dataclass
class PriceIngestReport:
    symbols_ok: int = 0
    rows_upserted: int = 0
    failures: dict[str, str] = field(default_factory=dict)


def upsert_bars(session: Session, symbol: str, bars: pd.DataFrame, source: str) -> int:
    """Insert or refresh bars for one symbol (re-running is safe). Returns rows written."""
    rows: list[dict[str, object]] = [
        {
            "symbol": symbol,
            "date": pd.Timestamp(rec["date"]).date(),
            **{c: float(rec[c]) for c in ("open", "high", "low", "close", "adj_close", "adj_open")},
            "volume": int(rec["volume"]),
            "source": source,
        }
        for rec in bars.rename_axis("date").reset_index().to_dict("records")
    ]
    if not rows:
        return 0
    stmt = insert(PriceDaily).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[PriceDaily.symbol, PriceDaily.date],
        set_={c: stmt.excluded[c] for c in rows[0] if c not in ("symbol", "date")},
    )
    session.execute(stmt)
    session.commit()
    return len(rows)


def ingest_prices(
    session: Session, source: PriceSource, symbols: list[str], start: date, end: date
) -> PriceIngestReport:
    """Fetch and store bars for each symbol; failures are recorded per symbol."""
    report = PriceIngestReport()
    for symbol in symbols:
        try:
            bars = source.fetch_daily(symbol, start, end)
            report.rows_upserted += upsert_bars(session, symbol, bars, source.name)
            report.symbols_ok += 1
            log.info("%s: %d bars", symbol, len(bars))
        except SourceError as exc:
            session.rollback()
            report.failures[symbol] = str(exc)
            log.error("%s: %s", symbol, exc)
    return report
