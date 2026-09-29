"""API endpoints against the test Postgres with seeded rows and a scripted LLM provider."""

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from newsalpha.api.app import create_app
from newsalpha.api.deps import data_dir, default_signal_source, get_provider
from newsalpha.db.models import Announcement, BacktestRun, Company, Event, Signal
from newsalpha.db.session import get_engine
from newsalpha.extraction.prompts import load_prompt
from newsalpha.extraction.providers import LLMResponse

pytestmark = pytest.mark.db
BACKEND = Path(__file__).resolve().parents[1]
VALID: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "llm" / "valid_signals.json").read_text()
)
TICKER = "ZZAPI"
GROUP = "00000000-0000-0000-0000-00000000api0"


class Scripted:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **_kw: Any) -> LLMResponse:
        self.calls += 1
        return LLMResponse(json.dumps(VALID), 100, 0, 20, 30)


@pytest.fixture
def api(live_db: None, tmp_path: Path) -> Iterator[tuple[TestClient, Scripted, list[int]]]:
    command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")
    source = default_signal_source()
    # Seeded rows must carry the real prompt hash, or the runner refuses to mix results.
    prompt_sha = load_prompt(source.prompt_version, BACKEND / "prompts").sha256
    with Session(get_engine()) as s:
        company = Company(ticker=TICKER, name="Api Co", cik=9_900_321, sector="Tech")
        s.add(company)
        s.flush()
        ids = []
        (tmp_path / "raw").mkdir()
        for i in range(3):
            (tmp_path / "raw" / f"{i}.txt").write_text(f"Release {i}: raised outlook.", "utf-8")
            ann = Announcement(
                company_id=company.id,
                source="apitest",
                source_id=f"zzapi-{i}",
                accepted_at=datetime(2024, 3, 1 + i, 21, tzinfo=UTC),
                form_type="8-K",
                item_codes=["2.02"],
                url=f"https://example.invalid/{i}",
                raw_text_uri=f"raw/{i}.txt",
                text_hash=f"zzapi-hash-{i}",
            )
            s.add(ann)
            s.flush()
            ids.append(ann.id)
        for aid in ids[:2]:  # the third has no signal yet
            s.add(
                Signal(
                    announcement_id=aid,
                    model=source.model,
                    prompt_version=source.prompt_version,
                    prompt_sha256=prompt_sha,
                    document_hash="x",
                    status="ok",
                    payload=VALID,
                    error=None,
                    attempts=1,
                    truncated=False,
                    cache_hit=False,
                    input_tokens=10,
                    cached_input_tokens=0,
                    output_tokens=5,
                    cost_usd=0.001,
                    latency_ms=50,
                )
            )
        s.add(
            Event(
                announcement_id=ids[0],
                t0_date=date(2024, 3, 4),
                entry_time=datetime(2024, 3, 4, 14, 30, tzinfo=UTC),
                entry_price=10.0,
                bench_entry_price=400.0,
                gap_abnormal=0.01,
                ar_1=0.02,
                ar_3=0.03,
                ar_5=None,
            )
        )
        s.add(
            BacktestRun(
                run_group=GROUP,
                strategy="llm_composite",
                period="in_sample",
                config={"fitted": {}},
                metrics={"sharpe": 1.0},
                equity_curve=[["2024-03-04", 1.0, 0.0]],
            )
        )
        s.commit()

        app = create_app()
        provider = Scripted()
        app.dependency_overrides[get_provider] = lambda: provider
        app.dependency_overrides[data_dir] = lambda: tmp_path
        yield TestClient(app), provider, ids

        s.execute(delete(BacktestRun).where(BacktestRun.run_group == GROUP))
        s.execute(delete(Event).where(Event.announcement_id.in_(ids)))
        s.execute(delete(Signal).where(Signal.announcement_id.in_(ids)))
        s.execute(delete(Announcement).where(Announcement.id.in_(ids)))
        s.execute(delete(Company).where(Company.ticker == TICKER))
        s.commit()


def test_companies_and_announcement_list(api: tuple[TestClient, Scripted, list[int]]) -> None:
    client, _, ids = api
    companies = {c["ticker"]: c for c in client.get("/companies").json()}
    assert companies[TICKER]["n_announcements"] == 3

    page = client.get("/announcements", params={"ticker": "zzapi", "page_size": 2}).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    assert [i["id"] for i in page["items"]] == [ids[2], ids[1]]  # newest first
    assert page["items"][0]["signal"] is None  # no signal yet: shown as missing, not faked
    assert page["items"][1]["signal"]["guidance_direction"] == "raised"

    # Dates are US/Eastern: accepted 2024-03-02 21:00 UTC is 16:00 ET on 2024-03-02.
    one_day = client.get(
        "/announcements", params={"ticker": TICKER, "from": "2024-03-02", "to": "2024-03-02"}
    ).json()
    assert [i["id"] for i in one_day["items"]] == [ids[1]]


def test_announcement_detail(api: tuple[TestClient, Scripted, list[int]]) -> None:
    client, _, ids = api
    body = client.get(f"/announcements/{ids[0]}").json()
    assert body["text"] == "Release 0: raised outlook." and body["text_available"]
    assert len(body["signals"]) == 1 and body["signals"][0]["cost_usd"] == 0.001
    assert body["event"]["ar_1"] == 0.02 and body["event"]["ar_5"] is None
    assert client.get("/announcements/999999999").status_code == 404


def test_latest_signals_skip_announcements_without_signals(
    api: tuple[TestClient, Scripted, list[int]],
) -> None:
    client, _, ids = api
    mine = [
        a
        for a in client.get("/signals/latest", params={"limit": 200}).json()
        if a["ticker"] == TICKER
    ]
    assert [a["id"] for a in mine] == [ids[1], ids[0]]


def test_extract_on_demand_pays_once(api: tuple[TestClient, Scripted, list[int]]) -> None:
    client, provider, ids = api
    first = client.post(f"/extract/{ids[2]}")
    assert first.status_code == 200 and first.json()["status"] == "ok"
    assert provider.calls == 1
    again = client.post(f"/extract/{ids[2]}")
    assert again.json()["id"] == first.json()["id"] and provider.calls == 1  # cached
    assert client.post("/extract/999999999").status_code == 404


def test_backtest_endpoints(api: tuple[TestClient, Scripted, list[int]]) -> None:
    client, _, _ = api
    group = client.get("/backtests", params={"run_group": GROUP}).json()
    assert group["runs"][0]["equity_curve"] == [["2024-03-04", 1.0, 0.0]]
    no_curves = client.get("/backtests", params={"run_group": GROUP, "curves": False}).json()
    assert no_curves["runs"][0]["equity_curve"] is None
    run_id = group["runs"][0]["id"]
    assert client.get(f"/backtests/{run_id}").json()["metrics"] == {"sharpe": 1.0}
    assert client.get("/backtests/999999999").status_code == 404


def test_openapi_lists_every_prd_endpoint(api: tuple[TestClient, Scripted, list[int]]) -> None:
    paths = api[0].get("/openapi.json").json()["paths"]
    for p in [
        "/health",
        "/companies",
        "/announcements",
        "/announcements/{announcement_id}",
        "/signals/latest",
        "/extract/{announcement_id}",
        "/events/summary",
        "/backtests",
        "/backtests/{run_id}",
        "/evals",
    ]:
        assert p in paths
    assert "post" in paths["/backtests"] and "post" in paths["/extract/{announcement_id}"]
