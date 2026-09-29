"""Companies, announcements and their signals."""

from datetime import date, datetime, time
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from newsalpha.api.deps import SignalSource, data_dir, default_signal_source
from newsalpha.api.schemas import (
    AnnouncementDetail,
    AnnouncementOut,
    AnnouncementPage,
    CompanyOut,
    EventOut,
    SignalOut,
    SignalSummary,
)
from newsalpha.core.time_rules import EASTERN
from newsalpha.db.models import Announcement, Company, Event, Signal
from newsalpha.db.session import get_session

router = APIRouter(tags=["announcements"])
SessionDep = Annotated[Session, Depends(get_session)]
SourceDep = Annotated[SignalSource, Depends(default_signal_source)]


def _summary(signal: Signal | None) -> SignalSummary | None:
    if signal is None or signal.status != "ok" or signal.payload is None:
        return None
    p: dict[str, Any] = signal.payload
    return SignalSummary(
        model=signal.model,
        prompt_version=signal.prompt_version,
        guidance_direction=p["guidance_direction"],
        revenue_vs_expectation=p["revenue_vs_expectation"],
        eps_vs_expectation=p["eps_vs_expectation"],
        management_tone=p["management_tone"],
        summary=p["summary"],
    )


def _out(ann: Announcement, company: Company, signal: Signal | None) -> AnnouncementOut:
    return AnnouncementOut(
        id=ann.id,
        ticker=company.ticker,
        company_name=company.name,
        source=ann.source,
        source_id=ann.source_id,
        accepted_at=ann.accepted_at,
        form_type=ann.form_type,
        item_codes=list(ann.item_codes),
        url=ann.url,
        signal=_summary(signal),
    )


def _with_signal(source: SignalSource) -> Select[Announcement, Company, Signal]:
    """Announcements joined to their company and (if any) the default model's signal."""
    return (
        select(Announcement, Company, Signal)
        .join(Company, Company.id == Announcement.company_id)
        .outerjoin(
            Signal,
            (Signal.announcement_id == Announcement.id)
            & (Signal.model == source.model)
            & (Signal.prompt_version == source.prompt_version),
        )
    )


@router.get("/companies", response_model=list[CompanyOut])
def list_companies(session: SessionDep) -> list[CompanyOut]:
    rows = session.execute(
        select(Company, func.count(Announcement.id))
        .outerjoin(Announcement, Announcement.company_id == Company.id)
        .group_by(Company.id)
        .order_by(Company.ticker)
    ).all()
    return [
        CompanyOut(
            id=c.id,
            ticker=c.ticker,
            name=c.name,
            cik=c.cik,
            sector=c.sector,
            exchange=c.exchange,
            n_announcements=n,
        )
        for c, n in rows
    ]


@router.get("/announcements", response_model=AnnouncementPage)
def list_announcements(
    session: SessionDep,
    source: SourceDep,
    ticker: str | None = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AnnouncementPage:
    """Newest first. ``from``/``to`` are inclusive US/Eastern dates of acceptance."""
    stmt = _with_signal(source)
    if ticker:
        stmt = stmt.where(Company.ticker == ticker.upper())
    if from_:
        stmt = stmt.where(Announcement.accepted_at >= datetime.combine(from_, time(), EASTERN))
    if to:
        stmt = stmt.where(Announcement.accepted_at < datetime.combine(to, time.max, EASTERN))
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.execute(
        stmt.order_by(Announcement.accepted_at.desc(), Announcement.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return AnnouncementPage(
        items=[_out(a, c, s) for a, c, s in rows], total=total, page=page, page_size=page_size
    )


@router.get("/announcements/{announcement_id}", response_model=AnnouncementDetail)
def get_announcement(
    announcement_id: int,
    session: SessionDep,
    source: SourceDep,
    base_dir: Annotated[Path, Depends(data_dir)],
) -> AnnouncementDetail:
    """One announcement with its text, every stored signal and its event (if built)."""
    row = session.execute(_with_signal(source).where(Announcement.id == announcement_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="announcement not found")
    ann, company, default_signal = row
    path = base_dir / ann.raw_text_uri
    text_available = path.exists()
    signals = session.scalars(
        select(Signal).where(Signal.announcement_id == ann.id).order_by(Signal.created_at.desc())
    ).all()
    event = session.scalar(select(Event).where(Event.announcement_id == ann.id))
    return AnnouncementDetail(
        **_out(ann, company, default_signal).model_dump(),
        text=path.read_text(encoding="utf-8") if text_available else "",
        text_available=text_available,
        signals=[SignalOut.model_validate(s, from_attributes=True) for s in signals],
        event=EventOut.model_validate(event, from_attributes=True) if event else None,
    )


@router.get("/signals/latest", response_model=list[AnnouncementOut])
def latest_signals(
    session: SessionDep,
    source: SourceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> list[AnnouncementOut]:
    """The most recent announcements that have an ok signal from the default model/prompt."""
    rows = session.execute(
        _with_signal(source)
        .where(Signal.status == "ok")
        .order_by(Announcement.accepted_at.desc(), Announcement.id.desc())
        .limit(limit)
    ).all()
    return [_out(a, c, s) for a, c, s in rows]
