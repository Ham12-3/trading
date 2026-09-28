"""SEC EDGAR 8-K source: earnings releases (Item 2.02) and their Exhibit 99.1 text.

Endpoints (official, no scraping of HTML listings):

* ``https://www.sec.gov/files/company_tickers_exchange.json`` - ticker -> CIK, exchange
* ``https://data.sec.gov/submissions/CIK##########.json``   - filing index per company
* ``https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{accession}.txt`` - full submission

The full submission's SEC header carries ``<ACCEPTANCE-DATETIME>`` in US/Eastern, which is the
point-in-time anchor for everything downstream.
"""

import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from newsalpha.sources.base import AnnouncementRecord, CompanyRef, FilingRef, SourceError

log = logging.getLogger(__name__)

EASTERN = ZoneInfo("America/New_York")
TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SUBMISSIONS_PAGE_URL = "https://data.sec.gov/submissions/{name}"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{accession}.txt"
INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{accession}-index.htm"

EARNINGS_ITEM = "2.02"
FORM_TYPES = frozenset({"8-K"})
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
INLINE_TAGS = ["a", "b", "i", "u", "em", "strong", "sup", "sub", "span", "font", "small"]


class RateLimiter:
    """Spaces calls at least ``1 / rate`` seconds apart (thread-safe)."""

    def __init__(self, rate_per_second: float) -> None:
        if not 0 < rate_per_second <= 10:
            raise ValueError("SEC fair access allows at most 10 requests per second")
        self._interval = 1.0 / rate_per_second
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now < self._next_at:
                time.sleep(self._next_at - now)
                now = self._next_at
            self._next_at = now + self._interval


class EdgarClient:
    """HTTP client with the required User-Agent, rate limiting and retry on 429/5xx."""

    def __init__(
        self,
        user_agent: str,
        max_requests_per_second: float = 5.0,
        *,
        max_retries: int = 4,
        backoff_seconds: float = 1.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._limiter = RateLimiter(max_requests_per_second)
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self._http = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=30.0,
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def get(self, url: str) -> httpx.Response:
        """GET with retries; raises ``SourceError`` with the URL and status on failure."""
        for attempt in range(self._max_retries + 1):
            self._limiter.wait()
            try:
                resp = self._http.get(url)
            except httpx.HTTPError as exc:
                if attempt == self._max_retries:
                    raise SourceError(f"EDGAR request failed for {url}: {exc}") from exc
            else:
                if resp.status_code == 200:
                    return resp
                if resp.status_code not in RETRY_STATUSES or attempt == self._max_retries:
                    raise SourceError(f"EDGAR returned HTTP {resp.status_code} for {url}")
            delay = self._backoff * 2**attempt
            log.warning("EDGAR retry %d for %s in %.1fs", attempt + 1, url, delay)
            time.sleep(delay)
        raise AssertionError("unreachable")

    def get_json(self, url: str) -> Any:
        return self.get(url).json()

    def get_text(self, url: str) -> str:
        return self.get(url).text


@dataclass(frozen=True)
class TickerInfo:
    cik: int
    name: str
    exchange: str | None


def sec_ticker(ticker: str) -> str:
    """EDGAR spells share classes with a dash (BRK.B -> BRK-B)."""
    return ticker.replace(".", "-").upper()


def parse_ticker_map(payload: dict[str, Any]) -> dict[str, TickerInfo]:
    """Parse ``company_tickers_exchange.json`` ({"fields": [...], "data": [[...], ...]})."""
    fields = payload["fields"]
    idx = {name: fields.index(name) for name in ("cik", "name", "ticker", "exchange")}
    out: dict[str, TickerInfo] = {}
    for row in payload["data"]:
        ticker = str(row[idx["ticker"]]).upper()
        out.setdefault(
            ticker,
            TickerInfo(
                cik=int(row[idx["cik"]]),
                name=str(row[idx["name"]]),
                exchange=row[idx["exchange"]] or None,
            ),
        )
    return out


def parse_filing_table(table: dict[str, list[Any]], since: date) -> list[FilingRef]:
    """Select 8-K filings with Item 2.02 filed on/after ``since`` from a columnar index."""
    out: list[FilingRef] = []
    for accession, form, filed, items in zip(
        table["accessionNumber"], table["form"], table["filingDate"], table["items"], strict=True
    ):
        codes = tuple(c.strip() for c in str(items or "").split(",") if c.strip())
        filed_on = date.fromisoformat(filed)
        if form in FORM_TYPES and EARNINGS_ITEM in codes and filed_on >= since:
            out.append(
                FilingRef(source_id=accession, filed_on=filed_on, form_type=form, item_codes=codes)
            )
    return out


_ACCEPTANCE_RE = re.compile(r"<ACCEPTANCE-DATETIME>(\d{14})")
_DOCUMENT_RE = re.compile(r"<DOCUMENT>(.*?)</DOCUMENT>", re.DOTALL)
_TAG_RE = {tag: re.compile(rf"<{tag}>([^\n<]*)") for tag in ("TYPE", "FILENAME")}
_TEXT_RE = re.compile(r"<TEXT>(.*?)</TEXT>", re.DOTALL)


@dataclass(frozen=True)
class SubmissionDocument:
    type: str
    filename: str
    body: str


def parse_acceptance(submission: str) -> datetime:
    """Acceptance time from the SEC header, as an aware UTC datetime.

    EDGAR writes it as ``YYYYMMDDHHMMSS`` in US/Eastern local time.
    """
    match = _ACCEPTANCE_RE.search(submission)
    if match is None:
        raise SourceError("submission has no <ACCEPTANCE-DATETIME> header")
    local = datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=EASTERN)
    return local.astimezone(ZoneInfo("UTC"))


def parse_documents(submission: str) -> list[SubmissionDocument]:
    """Split a full-text submission into its documents."""
    docs = []
    for block in _DOCUMENT_RE.findall(submission):
        type_m = _TAG_RE["TYPE"].search(block)
        name_m = _TAG_RE["FILENAME"].search(block)
        text_m = _TEXT_RE.search(block)
        docs.append(
            SubmissionDocument(
                type=type_m.group(1).strip().upper() if type_m else "",
                filename=name_m.group(1).strip() if name_m else "",
                body=text_m.group(1) if text_m else "",
            )
        )
    return docs


def pick_press_release(docs: list[SubmissionDocument]) -> SubmissionDocument | None:
    """Exhibit 99.1 if present, else the first EX-99.x exhibit, else ``None``."""
    for doc in docs:
        if doc.type == "EX-99.1":
            return doc
    for doc in docs:
        if doc.type.startswith("EX-99"):
            return doc
    return None


def html_to_text(body: str) -> str:
    """Readable plain text from an exhibit (HTML or plain), whitespace normalised."""
    if re.search(r"<(html|body|p|div|table|font)\b", body, re.IGNORECASE):
        soup = BeautifulSoup(body, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        # Inline markup (e.g. a <sup>(R)</sup>) must not break a sentence across lines.
        for tag in soup(INLINE_TAGS):
            tag.unwrap()
        soup.smooth()
        text = soup.get_text("\n")
    else:
        text = body
    text = text.replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


class EdgarSource:
    """``AnnouncementSource`` for US 8-K earnings releases."""

    name = "edgar"

    def __init__(self, client: EdgarClient) -> None:
        self._client = client

    def ticker_map(self) -> dict[str, TickerInfo]:
        return parse_ticker_map(self._client.get_json(TICKERS_URL))

    def list_filings(self, company: CompanyRef, since: date) -> list[FilingRef]:
        payload = self._client.get_json(SUBMISSIONS_URL.format(cik=company.cik))
        filings = parse_filing_table(payload["filings"]["recent"], since)
        # Older filings live in paginated files; fetch only pages overlapping the window.
        for page in payload["filings"].get("files", []):
            if date.fromisoformat(page["filingTo"]) >= since:
                table = self._client.get_json(SUBMISSIONS_PAGE_URL.format(name=page["name"]))
                filings.extend(parse_filing_table(table, since))
        unique = {f.source_id: f for f in filings}
        return sorted(unique.values(), key=lambda f: f.filed_on)

    def fetch(self, company: CompanyRef, filing: FilingRef) -> AnnouncementRecord | None:
        accession = filing.source_id
        parts = {
            "cik": company.cik,
            "acc_nodash": accession.replace("-", ""),
            "accession": accession,
        }
        submission = self._client.get_text(ARCHIVE_URL.format(**parts))
        exhibit = pick_press_release(parse_documents(submission))
        if exhibit is None:
            log.warning("%s %s: no EX-99 exhibit, skipped", company.ticker, accession)
            return None
        text = html_to_text(exhibit.body)
        if not text:
            log.warning("%s %s: EX-99 exhibit is empty, skipped", company.ticker, accession)
            return None
        return AnnouncementRecord(
            source=self.name,
            source_id=accession,
            accepted_at=parse_acceptance(submission),
            form_type=filing.form_type,
            item_codes=filing.item_codes,
            url=INDEX_URL.format(**parts),
            text=text,
        )
