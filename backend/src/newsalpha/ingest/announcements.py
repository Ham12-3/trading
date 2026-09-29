"""Ingest earnings announcements for the universe into ``companies`` and ``announcements``."""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from newsalpha.core.universe import Universe
from newsalpha.db.models import Announcement, Company
from newsalpha.sources.base import (
    AnnouncementRecord,
    AnnouncementSource,
    CompanyRef,
    FilingRef,
    SourceError,
)
from newsalpha.sources.edgar import TickerInfo, sec_ticker

log = logging.getLogger(__name__)


@dataclass
class AnnouncementIngestReport:
    companies: int = 0
    filings_found: int = 0
    inserted: int = 0
    already_stored: int = 0
    no_exhibit: int = 0
    failures: dict[str, str] = field(default_factory=dict)  # ticker or accession -> error


def store_text(data_dir: Path, record: AnnouncementRecord, cik: int) -> tuple[str, str]:
    """Write announcement text under ``data_dir``; return (uri relative to data_dir, sha256)."""
    digest = hashlib.sha256(record.text.encode("utf-8")).hexdigest()
    path = data_dir / "raw" / record.source / str(cik) / f"{record.source_id}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.text, encoding="utf-8", newline="\n")
    return path.relative_to(data_dir).as_posix(), digest


def upsert_companies(
    session: Session, universe: Universe, ticker_map: dict[str, TickerInfo]
) -> tuple[dict[str, Company], dict[str, str]]:
    """Insert/update universe companies. Returns (ticker -> Company, ticker -> error)."""
    errors: dict[str, str] = {}
    for member in universe.companies:
        info = ticker_map.get(sec_ticker(member.lookup_ticker))
        if info is None:
            errors[member.ticker] = "ticker not found in SEC company_tickers_exchange.json"
            continue
        stmt = insert(Company).values(
            ticker=member.ticker,
            name=member.name,
            cik=info.cik,
            sector=member.sector,
            exchange=info.exchange,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Company.ticker],
            set_={
                "name": stmt.excluded.name,
                "cik": stmt.excluded.cik,
                "sector": stmt.excluded.sector,
                "exchange": stmt.excluded.exchange,
            },
        )
        session.execute(stmt)
    session.commit()
    companies = {c.ticker: c for c in session.scalars(select(Company))}
    return {t: c for t, c in companies.items() if t in universe.tickers}, errors


def ingest_company(
    session: Session,
    source: AnnouncementSource,
    company: Company,
    since: date,
    data_dir: Path,
    report: AnnouncementIngestReport,
    predecessor_ciks: tuple[int, ...] = (),
) -> None:
    """Fetch and store new announcements for one company, across its current and predecessor
    CIKs. Existing rows are not re-downloaded."""
    stored = set(
        session.scalars(
            select(Announcement.source_id).where(
                Announcement.source == source.name, Announcement.company_id == company.id
            )
        )
    )
    for cik in (company.cik, *predecessor_ciks):
        ref = CompanyRef(ticker=company.ticker, cik=cik)
        filings = source.list_filings(ref, since)
        report.filings_found += len(filings)
        _store_filings(session, source, company, ref, filings, stored, data_dir, report)


def _store_filings(
    session: Session,
    source: AnnouncementSource,
    company: Company,
    ref: CompanyRef,
    filings: list[FilingRef],
    stored: set[str],
    data_dir: Path,
    report: AnnouncementIngestReport,
) -> None:
    for filing in filings:
        if filing.source_id in stored:
            report.already_stored += 1
            continue
        try:
            record = source.fetch(ref, filing)
        except SourceError as exc:
            report.failures[f"{company.ticker} {filing.source_id}"] = str(exc)
            log.error("%s %s: %s", company.ticker, filing.source_id, exc)
            continue
        if record is None:
            report.no_exhibit += 1
            continue
        uri, digest = store_text(data_dir, record, ref.cik)
        session.add(
            Announcement(
                company_id=company.id,
                source=record.source,
                source_id=record.source_id,
                accepted_at=record.accepted_at,
                form_type=record.form_type,
                item_codes=list(record.item_codes),
                url=record.url,
                raw_text_uri=uri,
                text_hash=digest,
            )
        )
        session.commit()
        stored.add(record.source_id)
        report.inserted += 1


def ingest_announcements(
    session: Session,
    source: AnnouncementSource,
    companies: dict[str, Company],
    since: date,
    data_dir: Path,
    report: AnnouncementIngestReport,
    predecessor_ciks: dict[str, tuple[int, ...]] | None = None,
) -> AnnouncementIngestReport:
    """Ingest every company; one company's failure is recorded and does not stop the rest."""
    predecessor_ciks = predecessor_ciks or {}
    for ticker, company in sorted(companies.items()):
        try:
            ingest_company(
                session,
                source,
                company,
                since,
                data_dir,
                report,
                predecessor_ciks.get(ticker, ()),
            )
            report.companies += 1
            log.info("%s done", ticker)
        except SourceError as exc:
            session.rollback()
            report.failures[ticker] = str(exc)
            log.error("%s: %s", ticker, exc)
    return report
