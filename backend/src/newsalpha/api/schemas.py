"""Typed response models shared by routers."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class CompanyOut(BaseModel):
    id: int
    ticker: str
    name: str
    cik: int
    sector: str | None
    exchange: str | None
    n_announcements: int


class SignalOut(BaseModel):
    id: int
    announcement_id: int
    model: str
    prompt_version: str
    status: str
    payload: dict[str, Any] | None
    error: str | None
    truncated: bool
    cache_hit: bool
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    created_at: datetime


class SignalSummary(BaseModel):
    """The fields the feed shows; None when the default model has no ok signal yet."""

    model: str
    prompt_version: str
    guidance_direction: str
    revenue_vs_expectation: str
    eps_vs_expectation: str
    management_tone: float
    summary: str


class AnnouncementOut(BaseModel):
    id: int
    ticker: str
    company_name: str
    source: str
    source_id: str
    accepted_at: datetime
    form_type: str
    item_codes: list[str]
    url: str
    signal: SignalSummary | None


class AnnouncementPage(BaseModel):
    items: list[AnnouncementOut]
    total: int
    page: int
    page_size: int


class EventOut(BaseModel):
    t0_date: date
    entry_price: float | None
    gap_abnormal: float | None
    ar_1: float | None
    ar_3: float | None
    ar_5: float | None


class AnnouncementDetail(AnnouncementOut):
    text: str
    text_available: bool
    signals: list[SignalOut]
    event: EventOut | None
