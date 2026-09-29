"""EDGAR parsing and client behaviour against synthetic fixtures (no network)."""

import json
import time
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from newsalpha.sources.base import CompanyRef, SourceError
from newsalpha.sources.edgar import (
    EdgarClient,
    EdgarSource,
    RateLimiter,
    html_to_text,
    parse_acceptance,
    parse_documents,
    parse_filing_table,
    parse_ticker_map,
    pick_press_release,
    sec_ticker,
)

FIX = Path(__file__).parent / "fixtures" / "edgar"
UA = "Test Runner test@example.com"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_acceptance_is_parsed_as_eastern_and_returned_in_utc() -> None:
    accepted = parse_acceptance(_read("submission_8k.txt"))
    # 16:05:12 EST (UTC-5) on 2024-01-23 -> 21:05:12 UTC.
    assert accepted == datetime(2024, 1, 23, 21, 5, 12, tzinfo=UTC)


def test_acceptance_across_dst() -> None:
    accepted = parse_acceptance("<ACCEPTANCE-DATETIME>20240725160000\n")
    assert accepted == datetime(2024, 7, 25, 20, 0, tzinfo=UTC)  # EDT, UTC-4


def test_missing_acceptance_header_is_an_error() -> None:
    with pytest.raises(SourceError, match="ACCEPTANCE-DATETIME"):
        parse_acceptance("<SEC-HEADER>nothing here</SEC-HEADER>")


def test_documents_and_press_release_selection() -> None:
    docs = parse_documents(_read("submission_8k.txt"))
    assert [d.type for d in docs] == ["8-K", "EX-99.1", "GRAPHIC"]
    pr = pick_press_release(docs)
    assert pr is not None and pr.filename == "exco-ex991.htm"


def test_press_release_falls_back_to_other_ex99() -> None:
    sub = "<DOCUMENT>\n<TYPE>EX-99.2\n<FILENAME>a.htm\n<TEXT>hello</TEXT>\n</DOCUMENT>"
    pr = pick_press_release(parse_documents(sub))
    assert pr is not None and pr.type == "EX-99.2"
    assert pick_press_release(parse_documents("<DOCUMENT>\n<TYPE>8-K\n</DOCUMENT>")) is None


def test_html_to_text_strips_markup_styles_and_entities() -> None:
    pr = pick_press_release(parse_documents(_read("submission_8k.txt")))
    assert pr is not None
    text = html_to_text(pr.body)
    assert "Example Co. Reports Fourth Quarter Results" in text
    assert "Revenue of $1.2 billion, up 8% year over year." in text
    assert "color: red" not in text and "<p>" not in text


def test_filing_table_filters_form_item_and_date() -> None:
    table = json.loads(_read("submissions.json"))["filings"]["recent"]
    found = parse_filing_table(table, since=date(2024, 1, 1))
    assert [f.source_id for f in found] == ["0000999999-24-000009", "0000999999-24-000001"]
    assert found[0].item_codes == ("2.02", "9.01")


def test_ticker_map_and_share_class_spelling() -> None:
    mapping = parse_ticker_map(json.loads(_read("company_tickers_exchange.json")))
    assert mapping["EXCO"].cik == 999999 and mapping["EXCO"].exchange == "NYSE"
    assert sec_ticker("BRK.B") == "BRK-B" and mapping[sec_ticker("BRK.B")].cik == 888888


def _mock_edgar(calls: list[httpx.Request]) -> httpx.MockTransport:
    routes = {
        "/submissions/CIK0000999999.json": _read("submissions.json"),
        "/submissions/CIK0000999999-submissions-001.json": _read("submissions_page_001.json"),
        "/Archives/edgar/data/999999/000099999924000001/0000999999-24-000001.txt": _read(
            "submission_8k.txt"
        ),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = routes.get(request.url.path)
        return httpx.Response(200, text=body) if body else httpx.Response(404)

    return httpx.MockTransport(handler)


def test_source_lists_recent_and_overlapping_pages_only() -> None:
    calls: list[httpx.Request] = []
    client = EdgarClient(UA, 10, transport=_mock_edgar(calls))
    filings = EdgarSource(client).list_filings(CompanyRef("EXCO", 999999), date(2024, 1, 1))
    assert [f.source_id for f in filings] == [
        "0000999999-24-000000",  # from the paginated file
        "0000999999-24-000001",
        "0000999999-24-000009",
    ]
    paths = [c.url.path for c in calls]
    assert "/submissions/CIK0000999999-submissions-002.json" not in paths  # outside the window
    assert all(c.headers["User-Agent"] == UA for c in calls)


def test_source_fetch_builds_record() -> None:
    calls: list[httpx.Request] = []
    source = EdgarSource(EdgarClient(UA, 10, transport=_mock_edgar(calls)))
    company = CompanyRef("EXCO", 999999)
    filing = next(
        f
        for f in source.list_filings(company, date(2024, 1, 1))
        if f.source_id == "0000999999-24-000001"
    )
    record = source.fetch(company, filing)
    assert record is not None
    assert record.accepted_at == datetime(2024, 1, 23, 21, 5, 12, tzinfo=UTC)
    assert record.url.endswith("/999999/000099999924000001/0000999999-24-000001-index.htm")
    assert "raised its full-year outlook" in record.text


def test_client_retries_on_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    statuses = iter([429, 503, 200])

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(next(statuses), json={"ok": True})

    client = EdgarClient(UA, 10, transport=httpx.MockTransport(handler))
    assert client.get_json("https://data.sec.gov/x.json") == {"ok": True}


def test_client_surfaces_non_retryable_errors() -> None:
    client = EdgarClient(UA, 10, transport=httpx.MockTransport(lambda _r: httpx.Response(403)))
    with pytest.raises(SourceError, match="HTTP 403"):
        client.get("https://www.sec.gov/blocked")


def test_client_gives_up_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    client = EdgarClient(
        UA, 10, max_retries=2, transport=httpx.MockTransport(lambda _r: httpx.Response(429))
    )
    with pytest.raises(SourceError, match="HTTP 429"):
        client.get("https://data.sec.gov/x.json")


def test_rate_limiter_enforces_spacing() -> None:
    limiter = RateLimiter(10)  # 100 ms apart
    start = time.monotonic()
    for _ in range(4):
        limiter.wait()
    assert time.monotonic() - start >= 0.3 - 0.01


def test_rate_limiter_refuses_more_than_sec_limit() -> None:
    with pytest.raises(ValueError, match="10 requests per second"):
        RateLimiter(11)


def test_inline_markup_does_not_split_sentences() -> None:
    body = "<html><body><p>CUPERTINO — Apple<sup>®</sup> today <b>announced</b> results.</p>"
    assert html_to_text(body) == "CUPERTINO — Apple® today announced results."
