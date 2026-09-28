"""Source interfaces. New markets (e.g. a UK RNS source) plug in here without touching callers."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

import pandas as pd


class SourceError(RuntimeError):
    """A data source failed. Callers must surface this, never paper over it."""


@dataclass(frozen=True)
class CompanyRef:
    """Identifiers a source needs to look up one company."""

    ticker: str
    cik: int


@dataclass(frozen=True)
class AnnouncementRecord:
    """One announcement as fetched, before it is stored."""

    source: str
    source_id: str  # unique within the source (EDGAR: accession number)
    accepted_at: datetime  # timezone-aware; the point-in-time anchor
    form_type: str
    item_codes: tuple[str, ...]
    url: str
    text: str


@dataclass(frozen=True)
class FilingRef:
    """A filing found in a listing, before its documents are downloaded."""

    source_id: str
    filed_on: date
    form_type: str
    item_codes: tuple[str, ...]


class AnnouncementSource(Protocol):
    name: str

    def list_filings(self, company: CompanyRef, since: date) -> list[FilingRef]:
        """Announcements of interest filed on or after ``since``."""
        ...

    def fetch(self, company: CompanyRef, filing: FilingRef) -> AnnouncementRecord | None:
        """Download one filing. ``None`` means it has no usable announcement text."""
        ...


class PriceSource(Protocol):
    name: str

    def fetch_daily(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Daily bars for [start, end], indexed by date, with columns
        open, high, low, close, adj_close, adj_open, volume. Raises ``SourceError`` on failure."""
        ...
