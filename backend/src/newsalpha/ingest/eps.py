"""Ingest EPS consensus/actuals and link each quarter to its earnings release."""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from newsalpha.core.time_rules import EASTERN
from newsalpha.db.models import Announcement, Company, EpsSurprise
from newsalpha.sources.base import SourceError
from newsalpha.sources.yahoo_estimates import EpsQuarter, surprise_pct

log = logging.getLogger(__name__)
MATCH_TOLERANCE_DAYS = 1  # Yahoo's report time is approximate; the SEC acceptance time is exact


class EstimatesSource(Protocol):
    name: str

    def fetch(self, symbol: str) -> list[EpsQuarter]: ...


@dataclass
class EpsIngestReport:
    companies_ok: int = 0
    quarters_stored: int = 0
    linked: int = 0
    failures: dict[str, str] = field(default_factory=dict)


def _et_date(ts: datetime) -> date:
    return ts.astimezone(EASTERN).date()


def match_quarters(
    announcements: list[tuple[int, datetime]], quarters: list[tuple[int, datetime]]
) -> dict[int, int]:
    """Pair announcements with quarters by nearest US/Eastern date within the tolerance.

    Each side is used at most once; the closest pairs win. Returns {quarter_id: announcement_id}.
    """
    candidates = []
    for aid, accepted in announcements:
        for qid, reported in quarters:
            gap = abs((_et_date(accepted) - _et_date(reported)).days)
            if gap <= MATCH_TOLERANCE_DAYS:
                candidates.append((gap, qid, aid))
    pairs: dict[int, int] = {}
    used_announcements: set[int] = set()
    for _, qid, aid in sorted(candidates):
        if qid not in pairs and aid not in used_announcements:
            pairs[qid] = aid
            used_announcements.add(aid)
    return pairs


def ingest_company_eps(
    session: Session, source: EstimatesSource, company: Company, lookup_symbol: str
) -> tuple[int, int]:
    """Store one company's quarters and (re)link them to its releases: (stored, linked)."""
    quarters = [q for q in source.fetch(lookup_symbol) if q.eps_reported is not None]
    for q in quarters:
        values = {
            "company_id": company.id,
            "earnings_at": q.earnings_at,
            "eps_estimate": q.eps_estimate,
            "eps_reported": q.eps_reported,
            "surprise_pct": surprise_pct(q.eps_reported, q.eps_estimate),
            "source": source.name,
        }
        stmt = insert(EpsSurprise).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[EpsSurprise.company_id, EpsSurprise.earnings_at],
            set_={k: stmt.excluded[k] for k in values if k not in ("company_id", "earnings_at")},
        )
        session.execute(stmt)
    session.flush()

    stored = session.execute(
        select(EpsSurprise.id, EpsSurprise.earnings_at).where(EpsSurprise.company_id == company.id)
    ).all()
    anns = session.execute(
        select(Announcement.id, Announcement.accepted_at).where(
            Announcement.company_id == company.id
        )
    ).all()
    pairs = match_quarters([(a, t) for a, t in anns], [(q, t) for q, t in stored])
    session.execute(
        update(EpsSurprise).where(EpsSurprise.company_id == company.id).values(announcement_id=None)
    )
    session.flush()
    for qid, aid in pairs.items():
        session.execute(
            update(EpsSurprise).where(EpsSurprise.id == qid).values(announcement_id=aid)
        )
    session.commit()
    return len(quarters), len(pairs)


def ingest_eps(
    session: Session,
    source: EstimatesSource,
    companies: list[tuple[Company, str]],
) -> EpsIngestReport:
    """Fetch and link EPS surprises for each (company, lookup symbol); failures are per company."""
    report = EpsIngestReport()
    for company, symbol in companies:
        try:
            stored, linked = ingest_company_eps(session, source, company, symbol)
            report.companies_ok += 1
            report.quarters_stored += stored
            report.linked += linked
            log.info("%s: %d quarters, %d linked", company.ticker, stored, linked)
        except SourceError as exc:
            session.rollback()
            report.failures[company.ticker] = str(exc)
            log.error("%s: %s", company.ticker, exc)
    return report
