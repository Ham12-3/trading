"""Extraction runner against the test Postgres with a scripted provider."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from newsalpha.core.stats import percentile
from newsalpha.db.models import Announcement, Company, Signal
from newsalpha.db.session import get_engine
from newsalpha.extraction.models_config import ExtractionSettings, ModelPrice
from newsalpha.extraction.prompts import Prompt, load_prompt
from newsalpha.extraction.providers import LLMResponse
from newsalpha.extraction.runner import PromptChangedError, run_extraction

pytestmark = pytest.mark.db
BACKEND = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND / "alembic.ini"
VALID = (Path(__file__).parent / "fixtures" / "llm" / "valid_signals.json").read_text("utf-8")
PRICE = ModelPrice(provider="fake", input_per_mtok=1, cached_input_per_mtok=0, output_per_mtok=1)
SETTINGS = ExtractionSettings(
    max_input_tokens=1000,
    max_output_tokens=500,
    concurrency=2,
    rate_limit_retries=0,
    rate_limit_backoff_seconds=1,
)
TICKER = "ZZEXTR"


class CountingProvider:
    """Valid output for every document except those whose text contains 'BROKEN'."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **kwargs: Any) -> LLMResponse:
        self.calls += 1
        text = "not json" if "BROKEN" in kwargs["user"] else VALID
        return LLMResponse(text, 100, 0, 50, 10)


@pytest.fixture
def setup(live_db: None, tmp_path: Path) -> Iterator[tuple[Session, Path, list[int]]]:
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    with Session(get_engine()) as s:
        company = Company(ticker=TICKER, name="Extract Co", cik=9_900_777, sector=None)
        s.add(company)
        s.flush()
        docs = {"a": "Same text", "b": "Same text", "c": "Different text", "d": "BROKEN text"}
        ids = []
        for i, (key, text) in enumerate(docs.items()):
            rel = f"raw/test/{key}.txt"
            (tmp_path / "raw" / "test").mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text(text, encoding="utf-8")
            ann = Announcement(
                company_id=company.id,
                source="test",
                source_id=f"zz-{key}",
                accepted_at=datetime(2024, 1, 10 + i, 21, 0, tzinfo=UTC),
                form_type="8-K",
                item_codes=["2.02"],
                url="https://example.invalid",
                raw_text_uri=rel,
                text_hash=f"hash-{text}",
            )
            s.add(ann)
            s.flush()
            ids.append(ann.id)
        s.commit()
        yield s, tmp_path, ids
        s.execute(delete(Signal).where(Signal.announcement_id.in_(ids)))
        s.execute(delete(Announcement).where(Announcement.id.in_(ids)))
        s.execute(delete(Company).where(Company.ticker == TICKER))
        s.commit()


def _run(session: Session, data_dir: Path, provider: CountingProvider, prompt: Prompt, **kw: Any):  # type: ignore[no-untyped-def]
    return run_extraction(
        session=session,
        provider=provider,
        model="fake-model",
        prompt=prompt,
        price=PRICE,
        settings=SETTINGS,
        data_dir=data_dir,
        **kw,
    )


def _signals(session: Session, ids: list[int]) -> dict[int, Signal]:
    rows = session.scalars(select(Signal).where(Signal.announcement_id.in_(ids)))
    return {r.announcement_id: r for r in rows}


def test_run_stores_signals_pays_once_per_text_and_records_failures(
    setup: tuple[Session, Path, list[int]],
) -> None:
    session, data_dir, ids = setup
    prompt = load_prompt("v1", BACKEND / "prompts")
    provider = CountingProvider()
    report = _run(session, data_dir, provider, prompt)

    # a and b share a text hash: one paid call. d fails validation twice.
    assert provider.calls == 1 + 1 + 2
    assert (report.documents, report.ok, report.failed, report.cache_hits) == (4, 3, 1, 1)
    rows = _signals(session, ids)
    assert rows[ids[0]].status == "ok" and rows[ids[0]].payload == json.loads(VALID)
    assert [rows[ids[0]].cache_hit, rows[ids[1]].cache_hit].count(True) == 1
    assert rows[ids[3]].status == "failed" and rows[ids[3]].attempts == 2
    assert "validation" in (rows[ids[3]].error or "")
    assert all(r.prompt_sha256 == prompt.sha256 for r in rows.values())

    # Re-running does nothing: ok rows are cached, failed rows wait for --retry-failed.
    again = _run(session, data_dir, CountingProvider(), prompt)
    assert again.documents == 0

    retry_provider = CountingProvider()
    retried = _run(session, data_dir, retry_provider, prompt, retry_failed=True)
    assert retried.documents == 1 and retry_provider.calls == 2


def test_edited_prompt_without_new_version_is_refused(
    setup: tuple[Session, Path, list[int]],
) -> None:
    session, data_dir, _ = setup
    prompt = load_prompt("v1", BACKEND / "prompts")
    _run(session, data_dir, CountingProvider(), prompt, limit=1)
    edited = Prompt(prompt.version, prompt.system + " edited", prompt.user_template, "0" * 64)
    with pytest.raises(PromptChangedError):
        _run(session, data_dir, CountingProvider(), edited)


def test_missing_text_file_is_a_recorded_failure(
    setup: tuple[Session, Path, list[int]], tmp_path: Path
) -> None:
    session, _, ids = setup
    empty_dir = tmp_path / "nothing-here"
    report = _run(
        session, empty_dir, CountingProvider(), load_prompt("v1", BACKEND / "prompts"), limit=1
    )
    assert report.failed == 1
    assert "cannot read" in (_signals(session, ids)[ids[0]].error or "")


def test_percentile() -> None:
    assert percentile([], 50) == 0.0
    assert percentile([10, 20, 30, 40], 50) == 20.0
    assert percentile(list(range(1, 101)), 95) == 95.0
