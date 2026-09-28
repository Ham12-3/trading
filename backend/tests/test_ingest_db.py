"""Ingestion against a real Postgres with fake sources: idempotent, errors surfaced."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from newsalpha.core.universe import Universe, UniverseMember
from newsalpha.db.models import Announcement, Company, PriceDaily
from newsalpha.db.session import get_engine
from newsalpha.ingest.announcements import (
    AnnouncementIngestReport,
    ingest_announcements,
    upsert_companies,
)
from newsalpha.ingest.prices import ingest_prices
from newsalpha.sources.base import AnnouncementRecord, CompanyRef, FilingRef, SourceError
from newsalpha.sources.edgar import TickerInfo

pytestmark = pytest.mark.db
ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
TEST_TICKERS = ("ZZTEST1", "ZZTEST2")


@pytest.fixture
def session(live_db: None) -> Iterator[Session]:
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    with Session(get_engine()) as s:
        yield s
        # Clean up only rows this test created.
        ids = select(Company.id).where(Company.ticker.in_(TEST_TICKERS))
        s.execute(delete(Announcement).where(Announcement.company_id.in_(ids)))
        s.execute(delete(Company).where(Company.ticker.in_(TEST_TICKERS)))
        s.execute(delete(PriceDaily).where(PriceDaily.symbol.in_(TEST_TICKERS)))
        s.commit()


class FakeAnnouncements:
    name = "fake"

    def __init__(self) -> None:
        self.fetches = 0

    def list_filings(self, company: CompanyRef, since: date) -> list[FilingRef]:
        if company.ticker == "ZZTEST2":
            raise SourceError("simulated outage")
        return [
            FilingRef(f"{company.cik}-a", date(2024, 1, 23), "8-K", ("2.02",)),
            FilingRef(f"{company.cik}-b", date(2024, 4, 25), "8-K", ("2.02",)),
        ]

    def fetch(self, company: CompanyRef, filing: FilingRef) -> AnnouncementRecord | None:
        self.fetches += 1
        if filing.source_id.endswith("-b"):
            return None  # no exhibit
        return AnnouncementRecord(
            source=self.name,
            source_id=filing.source_id,
            accepted_at=datetime(2024, 1, 23, 21, 5, tzinfo=UTC),
            form_type="8-K",
            item_codes=("2.02",),
            url="https://example.invalid/filing",
            text="Quarterly results text.",
        )


def test_announcement_ingest_is_idempotent_and_reports_failures(
    session: Session, tmp_path: Path
) -> None:
    universe = Universe(
        as_of="2023-09-18",
        source="test",
        benchmark="SPY",
        companies=(
            UniverseMember("ZZTEST1", "Test One", "Tech"),
            UniverseMember("ZZTEST2", "Test Two", "Tech"),
            UniverseMember("ZZMISSING", "Unmapped", "Tech"),
        ),
    )
    mapping = {
        "ZZTEST1": TickerInfo(9_900_001, "T1", "NYSE"),
        "ZZTEST2": TickerInfo(9_900_002, "T2", None),
    }
    companies, errors = upsert_companies(session, universe, mapping)
    assert set(companies) == set(TEST_TICKERS)
    assert "ZZMISSING" in errors

    source = FakeAnnouncements()
    report = ingest_announcements(
        session, source, companies, date(2024, 1, 1), tmp_path, AnnouncementIngestReport()
    )
    assert report.inserted == 1 and report.no_exhibit == 1
    assert "ZZTEST2" in report.failures

    stored = session.scalars(select(Announcement).where(Announcement.source == "fake")).one()
    assert stored.accepted_at == datetime(2024, 1, 23, 21, 5, tzinfo=UTC)
    assert (tmp_path / stored.raw_text_uri).read_text(encoding="utf-8") == "Quarterly results text."
    assert len(stored.text_hash) == 64

    # Second run: the stored filing is not downloaded again and no duplicate row appears.
    fetches_before = source.fetches
    again = ingest_announcements(
        session, source, companies, date(2024, 1, 1), tmp_path, AnnouncementIngestReport()
    )
    assert again.inserted == 0 and again.already_stored == 1
    assert source.fetches == fetches_before + 1  # only the exhibit-less filing is retried
    count = session.scalar(
        select(func.count()).select_from(Announcement).where(Announcement.source == "fake")
    )
    assert count == 1


class FakePrices:
    name = "fake"

    def fetch_daily(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        if symbol == "ZZTEST2":
            raise SourceError("no data")
        idx = pd.DatetimeIndex(
            [pd.Timestamp("2024-01-22"), pd.Timestamp("2024-01-23")], name="date"
        )
        return pd.DataFrame(
            {
                "open": [1.0, 2.0],
                "high": [1.5, 2.5],
                "low": [0.5, 1.5],
                "close": [1.2, 2.2],
                "adj_close": [1.2, 2.2],
                "adj_open": [1.0, 2.0],
                "volume": [10, 20],
            },
            index=idx,
        )


def test_price_ingest_upserts_and_reports_failures(session: Session) -> None:
    report = ingest_prices(
        session, FakePrices(), list(TEST_TICKERS), date(2024, 1, 1), date(2024, 1, 31)
    )
    assert report.symbols_ok == 1 and report.rows_upserted == 2
    assert "ZZTEST2" in report.failures
    # Stored under the snapshot symbol, fetched under the current one.
    renamed = ingest_prices(
        session,
        FakePrices(),
        ["ZZTEST1"],
        date(2024, 1, 1),
        date(2024, 1, 31),
        {"ZZTEST1": "ZZNEW"},
    )
    assert renamed.symbols_ok == 1
    n = session.scalar(
        select(func.count()).select_from(PriceDaily).where(PriceDaily.symbol == "ZZTEST1")
    )
    assert n == 2


class PredecessorAnnouncements(FakeAnnouncements):
    def list_filings(self, company: CompanyRef, since: date) -> list[FilingRef]:
        return [FilingRef(f"{company.cik}-a", date(2024, 1, 23), "8-K", ("2.02",))]


def test_filings_are_collected_from_predecessor_ciks(session: Session, tmp_path: Path) -> None:
    universe = Universe(
        as_of="2023-09-18",
        source="test",
        benchmark="SPY",
        companies=(UniverseMember("ZZTEST1", "Test One", "Tech", predecessor_ciks=(9_900_009,)),),
    )
    mapping = {"ZZTEST1": TickerInfo(9_900_001, "T1", "NYSE")}
    companies, _ = upsert_companies(session, universe, mapping)
    report = ingest_announcements(
        session,
        PredecessorAnnouncements(),
        companies,
        date(2024, 1, 1),
        tmp_path,
        AnnouncementIngestReport(),
        {"ZZTEST1": (9_900_009,)},
    )
    assert report.inserted == 2
    ids = set(session.scalars(select(Announcement.source_id).where(Announcement.source == "fake")))
    assert ids == {"9900001-a", "9900009-a"}
    assert (tmp_path / "raw" / "fake" / "9900009" / "9900009-a.txt").exists()
