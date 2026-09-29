"""events build + backtest run against the test Postgres with synthetic prices and signals."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from newsalpha.backtest.config import load_backtest_config
from newsalpha.backtest.events import build_events
from newsalpha.backtest.runner import run_backtest
from newsalpha.core.calendar import get_calendar
from newsalpha.db.models import (
    Announcement,
    BacktestRun,
    Company,
    Event,
    PriceDaily,
    Signal,
)
from newsalpha.db.session import get_engine

pytestmark = pytest.mark.db
BACKEND = Path(__file__).resolve().parents[1]
BENCH, MODEL = "ZZSPY", "fake-bt"
TICKERS = ("ZZBT1", "ZZBT2")


def _prices(symbol: str, drift: float) -> list[dict[str, object]]:
    rows, price = [], 100.0
    for d in get_calendar().trading_days(date(2024, 1, 2), date(2024, 3, 28)):
        o = price
        price *= 1 + drift
        rows.append(
            {
                "symbol": symbol,
                "date": d,
                "open": o,
                "high": price,
                "low": o,
                "close": price,
                "adj_close": price,
                "adj_open": o,
                "volume": 1,
                "source": "test",
            }
        )
    return rows


@pytest.fixture
def seeded(live_db: None) -> Iterator[Session]:
    command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")
    with Session(get_engine()) as s:
        s.add_all(PriceDaily(**r) for r in _prices(BENCH, 0.0005))
        s.add_all(PriceDaily(**r) for r in _prices("ZZBT1", 0.004))  # rises: longs should win
        s.add_all(PriceDaily(**r) for r in _prices("ZZBT2", -0.004))  # falls: shorts should win
        companies = [Company(ticker=t, name=t, cik=9_900_900 + i) for i, t in enumerate(TICKERS)]
        s.add_all(companies)
        s.flush()
        start = datetime(2024, 1, 8, 21, 0, tzinfo=UTC)  # 16:00 ET, after the close
        for i in range(16):  # weekly announcements for each company through March
            for c, guidance, tone in (
                (companies[0], "raised", 0.9),
                (companies[1], "lowered", 0.1),
            ):
                ann = Announcement(
                    company_id=c.id,
                    source="test",
                    source_id=f"{c.ticker}-{i}",
                    accepted_at=start + timedelta(days=5 * i),
                    form_type="8-K",
                    item_codes=["2.02"],
                    url="https://example.invalid",
                    raw_text_uri="x",
                    text_hash=f"{c.ticker}-{i}",
                )
                s.add(ann)
                s.flush()
                s.add(
                    Signal(
                        announcement_id=ann.id,
                        model=MODEL,
                        prompt_version="v1",
                        prompt_sha256="0",
                        document_hash="x",
                        status="ok",
                        error=None,
                        attempts=1,
                        truncated=False,
                        cache_hit=False,
                        input_tokens=0,
                        cached_input_tokens=0,
                        output_tokens=0,
                        cost_usd=0.0,
                        latency_ms=0,
                        payload={
                            "guidance_direction": guidance,
                            "revenue_vs_expectation": "unknown",
                            "eps_vs_expectation": "unknown",
                            "management_tone": tone,
                        },
                    )
                )
        s.commit()
        yield s
        ids = select(Announcement.id).where(Announcement.source == "test")
        s.execute(
            delete(BacktestRun).where(
                BacktestRun.config["config"]["signals"]["model"].astext == MODEL
            )
        )
        s.execute(delete(Event).where(Event.announcement_id.in_(ids)))
        s.execute(delete(Signal).where(Signal.model == MODEL))
        s.execute(delete(Announcement).where(Announcement.source == "test"))
        s.execute(delete(Company).where(Company.ticker.in_(TICKERS)))
        s.execute(delete(PriceDaily).where(PriceDaily.symbol.in_((BENCH, *TICKERS))))
        s.commit()


def test_events_and_backtest_end_to_end(seeded: Session) -> None:
    cal = get_calendar()
    report = build_events(seeded, cal, benchmark=BENCH)
    assert report.built == 32 and report.no_prices == 0
    first = seeded.scalars(select(Event).order_by(Event.t0_date)).first()
    assert first is not None and first.t0_date == date(2024, 1, 9)  # after close -> next day
    assert build_events(seeded, cal, benchmark=BENCH).built == 32  # idempotent upsert
    assert seeded.query(Event).count() == 32

    config = load_backtest_config(BACKEND / "config" / "backtest.yaml").model_copy(deep=True)
    config.signals.model = MODEL
    config.periods.in_sample.start, config.periods.in_sample.end = (
        date(2024, 1, 2),
        date(2024, 2, 9),
    )
    config.periods.out_of_sample.start = date(2024, 2, 12)
    config.periods.out_of_sample.end = date(2024, 3, 28)
    group, runs = run_backtest(seeded, config, cal, benchmark=BENCH)

    assert len(runs) == 6 and {r.run_group for r in runs} == {group}
    fitted = runs[0].config["fitted"]
    assert fitted["tone_center"] == pytest.approx(0.5)  # median of in-sample tones 0.9 / 0.1
    assert fitted["tuned_on"] == "in_sample" and len(runs[0].config["tuning_grid"]) == 16
    by = {(r.strategy, r.period): r for r in runs}
    llm_oos = by[("llm_composite", "out_of_sample")]
    assert llm_oos.metrics["n_long"] > 0 and llm_oos.metrics["n_short"] > 0
    assert llm_oos.metrics["total_return"] > 0  # long the riser, short the faller, hedged
    n_days = len(cal.trading_days(date(2024, 2, 12), date(2024, 3, 28)))
    assert len(llm_oos.equity_curve) == n_days
    assert by[("baseline_beat_miss", "in_sample")].metrics["n_trades"] == 0  # no beat/miss
