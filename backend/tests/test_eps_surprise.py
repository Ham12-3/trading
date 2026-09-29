"""EPS consensus: parsing, surprise maths, release matching, strategies, and DB ingestion."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from newsalpha.backtest.config import load_backtest_config
from newsalpha.backtest.runner import add_buckets
from newsalpha.backtest.strategy import eps_surprise_sides
from newsalpha.db.models import Announcement, Company, EpsSurprise
from newsalpha.db.session import get_engine
from newsalpha.ingest.eps import ingest_eps, match_quarters
from newsalpha.sources.base import SourceError
from newsalpha.sources.yahoo_estimates import EpsQuarter, normalise_earnings_dates, surprise_pct

ET = ZoneInfo("America/New_York")
BACKEND = Path(__file__).resolve().parents[1]


def test_surprise_pct() -> None:
    assert surprise_pct(1.09, 1.46) == pytest.approx((1.09 - 1.46) / 1.46)  # CVS Q3 2024 miss
    assert surprise_pct(-0.5, -1.0) == pytest.approx(0.5)  # smaller loss than expected is a beat
    assert surprise_pct(None, 1.0) is None and surprise_pct(1.0, 0.0) is None


def test_normalise_earnings_dates() -> None:
    idx = pd.DatetimeIndex(
        ["2026-10-28 08:00", "2024-11-06 06:00"], tz="America/New_York", name="Earnings Date"
    )
    raw = pd.DataFrame(
        {
            "EPS Estimate": [1.62, 1.46],
            "Reported EPS": [float("nan"), 1.09],
            "Surprise(%)": [float("nan"), -25.23],
        },
        index=idx,
    )
    q = normalise_earnings_dates(raw, "CVS")
    assert q[0].eps_reported is None  # future quarter: not reported yet
    assert q[1].eps_estimate == 1.46 and q[1].earnings_at.tzinfo is not None
    with pytest.raises(SourceError, match="missing columns"):
        normalise_earnings_dates(raw.drop(columns=["Reported EPS"]), "CVS")


def test_match_quarters_by_nearest_eastern_date() -> None:
    ann = [
        (1, datetime(2024, 11, 6, 11, 33, tzinfo=UTC)),  # 06:33 ET
        (2, datetime(2024, 10, 18, 10, 46, tzinfo=UTC)),  # special update, no earnings quarter
        (3, datetime(2024, 2, 1, 21, 30, tzinfo=UTC)),  # 16:30 ET
    ]
    quarters = [
        (10, datetime(2024, 11, 6, 6, 0, tzinfo=ET)),
        (11, datetime(2024, 2, 2, 8, 0, tzinfo=ET)),  # Yahoo date one day off: still matched
        (12, datetime(2023, 11, 1, 6, 0, tzinfo=ET)),  # before the study: unmatched
    ]
    assert match_quarters(ann, quarters) == {10: 1, 11: 3}


def test_match_uses_eastern_not_utc_date() -> None:
    # 2024-02-01 23:30 ET is already 2024-02-02 in UTC; a quarter on 2024-02-03 ET is two days off.
    ann = [(1, datetime(2024, 2, 2, 4, 30, tzinfo=UTC))]
    assert match_quarters(ann, [(10, datetime(2024, 2, 3, 8, 0, tzinfo=ET))]) == {}


def test_eps_surprise_sides_and_bucket() -> None:
    frame = pd.DataFrame({"eps_surprise_pct": [0.25, -0.25, 0.01, None]})
    assert eps_surprise_sides(frame, 0.02).tolist() == [1, -1, 0, 0]


def test_surprise_bucket_column() -> None:
    config = load_backtest_config(BACKEND / "config" / "backtest.yaml")
    frame = pd.DataFrame(
        {
            "t0": [date(2024, 3, 1)] * 4,
            "management_tone": [0.5] * 4,
            "revenue_vs_expectation": ["unknown"] * 4,
            "eps_vs_expectation": ["unknown"] * 4,
            "gap_abnormal": [0.0] * 4,
            "eps_surprise_pct": [0.05, -0.05, 0.0, None],
        }
    )
    buckets = add_buckets(frame, config)["eps_surprise_bucket"].tolist()
    assert buckets[:3] == ["beat", "miss", "inline"] and pd.isna(buckets[3])


class FakeEstimates:
    name = "fake"

    def fetch(self, symbol: str) -> list[EpsQuarter]:
        if symbol == "BROKEN":
            raise SourceError("simulated outage")
        return [
            EpsQuarter(datetime(2024, 3, 5, 6, 0, tzinfo=ET), 1.00, 1.10),
            EpsQuarter(datetime(2024, 6, 4, 6, 0, tzinfo=ET), 1.00, 0.90),
            EpsQuarter(datetime(2026, 12, 1, 6, 0, tzinfo=ET), 1.00, None),  # future: skipped
        ]


@pytest.fixture
def company(live_db: None) -> Iterator[tuple[Session, Company, list[int]]]:
    command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")
    with Session(get_engine()) as s:
        c = Company(ticker="ZZEPS", name="Eps Co", cik=9_900_888)
        s.add(c)
        s.flush()
        ids = []
        for i, day in enumerate(
            [datetime(2024, 3, 5, 11, 30, tzinfo=UTC), datetime(2024, 6, 4, 11, 30, tzinfo=UTC)]
        ):
            a = Announcement(
                company_id=c.id,
                source="epstest",
                source_id=f"zzeps-{i}",
                accepted_at=day,
                form_type="8-K",
                item_codes=["2.02"],
                url="https://example.invalid",
                raw_text_uri="x",
                text_hash="x",
            )
            s.add(a)
            s.flush()
            ids.append(a.id)
        s.commit()
        yield s, c, ids
        s.execute(delete(EpsSurprise).where(EpsSurprise.company_id == c.id))
        s.execute(delete(Announcement).where(Announcement.id.in_(ids)))
        s.execute(delete(Company).where(Company.id == c.id))
        s.commit()


def test_ingest_links_quarters_and_is_idempotent(
    company: tuple[Session, Company, list[int]],
) -> None:
    session, c, ids = company
    report = ingest_eps(session, FakeEstimates(), [(c, "ZZEPS")])
    assert (report.companies_ok, report.quarters_stored, report.linked) == (1, 2, 2)
    rows = {
        r.announcement_id: r
        for r in session.scalars(select(EpsSurprise).where(EpsSurprise.company_id == c.id))
    }
    assert rows[ids[0]].surprise_pct == pytest.approx(0.10)
    assert rows[ids[1]].surprise_pct == pytest.approx(-0.10)

    again = ingest_eps(session, FakeEstimates(), [(c, "ZZEPS")])
    assert again.linked == 2
    assert (
        len(session.scalars(select(EpsSurprise).where(EpsSurprise.company_id == c.id)).all()) == 2
    )

    failed = ingest_eps(session, FakeEstimates(), [(c, "BROKEN")])
    assert "ZZEPS" in failed.failures and failed.companies_ok == 0


def test_announcement_timestamps_unaffected(company: tuple[Session, Company, list[int]]) -> None:
    """Linking never moves the SEC timestamp: the event day still comes from acceptance time."""
    session, c, ids = company
    before = session.get(Announcement, ids[0])
    assert before is not None
    stamp = before.accepted_at
    ingest_eps(session, FakeEstimates(), [(c, "ZZEPS")])
    session.expire_all()
    after = session.get(Announcement, ids[0])
    assert after is not None and after.accepted_at == stamp
    assert stamp - datetime(2024, 3, 5, 11, 30, tzinfo=UTC) == timedelta(0)
