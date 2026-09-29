"""`run_eval` and GET /evals against the test Postgres with a scripted provider."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from newsalpha.api.app import create_app
from newsalpha.db.models import Announcement, Company, EvalRun, Signal
from newsalpha.db.session import get_engine
from newsalpha.eval.evaluate import GoldSetError, run_eval
from newsalpha.eval.gold import GoldLabels, GoldRecord, append_gold
from newsalpha.extraction.models_config import ExtractionSettings, ModelPrice
from newsalpha.extraction.prompts import load_prompt
from newsalpha.extraction.providers import LLMResponse

pytestmark = pytest.mark.db
BACKEND = Path(__file__).resolve().parents[1]
VALID: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "llm" / "valid_signals.json").read_text()
)
MODEL = "fake-eval-model"


class Scripted:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **_kw: Any) -> LLMResponse:
        self.calls += 1
        return LLMResponse(json.dumps(VALID), 100, 0, 20, 40)


@pytest.fixture
def db(live_db: None, tmp_path: Path) -> Iterator[tuple[Session, Path, Path]]:
    command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")
    with Session(get_engine()) as s:
        company = Company(ticker="ZZEVAL", name="Eval Co", cik=9_900_555)
        s.add(company)
        s.flush()
        (tmp_path / "raw").mkdir()
        ids = []
        for i in range(2):
            (tmp_path / "raw" / f"{i}.txt").write_text(f"release {i}", encoding="utf-8")
            ann = Announcement(
                company_id=company.id,
                source="test",
                source_id=f"zzeval-{i}",
                accepted_at=datetime(2024, 2, 1 + i, 21, tzinfo=UTC),
                form_type="8-K",
                item_codes=["2.02"],
                url="https://example.invalid",
                raw_text_uri=f"raw/{i}.txt",
                text_hash=f"zzeval-hash-{i}",
            )
            s.add(ann)
            s.flush()
            ids.append(ann.id)
        s.commit()
        gold_path = tmp_path / "gold.jsonl"
        for i, guidance in enumerate(["raised", "lowered"]):
            append_gold(
                GoldRecord(
                    source="test",
                    source_id=f"zzeval-{i}",
                    ticker="ZZEVAL",
                    labels=GoldLabels.model_validate(
                        {
                            "guidance_direction": guidance,
                            "revenue_vs_expectation": "beat",
                            "eps_vs_expectation": "unknown",
                            "management_tone": 0.6,
                        }
                    ),
                    labeller="tester",
                    labelled_at=datetime(2026, 9, 29, tzinfo=UTC),
                ),
                gold_path,
            )
        yield s, tmp_path, gold_path
        s.execute(delete(EvalRun).where(EvalRun.model == MODEL))
        s.execute(delete(Signal).where(Signal.announcement_id.in_(ids)))
        s.execute(delete(Announcement).where(Announcement.id.in_(ids)))
        s.execute(delete(Company).where(Company.ticker == "ZZEVAL"))
        s.commit()


def _kwargs(provider: Scripted, data_dir: Path, gold_path: Path) -> dict[str, Any]:
    return {
        "provider": provider,
        "model": MODEL,
        "prompt": load_prompt("v1", BACKEND / "prompts"),
        "price": ModelPrice(
            provider="fake", input_per_mtok=1, cached_input_per_mtok=0, output_per_mtok=1
        ),
        "settings": ExtractionSettings(
            max_input_tokens=1000,
            max_output_tokens=100,
            concurrency=1,
            rate_limit_retries=0,
            rate_limit_backoff_seconds=1,
        ),
        "data_dir": data_dir,
        "gold_path": gold_path,
        "sleep": lambda _s: None,
    }


def test_run_eval_extracts_only_gold_docs_scores_and_stores(
    db: tuple[Session, Path, Path],
) -> None:
    session, data_dir, gold_path = db
    provider = Scripted()
    run = run_eval(session=session, **_kwargs(provider, data_dir, gold_path))
    assert provider.calls == 2
    # Fixture payload says "raised" / "beat" / "unknown": guidance 1 of 2 right, others 2 of 2.
    assert run.metrics["fields"]["guidance_direction"]["accuracy"] == 0.5
    assert run.metrics["fields"]["revenue_vs_expectation"]["accuracy"] == 1.0
    assert run.n_gold == 2 and len(run.gold_sha256) == 64
    assert run.metrics["labellers"] == ["tester"] and run.metrics["gold_file"] == "gold.jsonl"

    # A second run reuses the stored signals: no new LLM calls.
    again = Scripted()
    run_eval(session=session, **_kwargs(again, data_dir, gold_path))
    assert again.calls == 0

    body = TestClient(create_app()).get("/evals").json()
    mine = [r for r in body if r["model"] == MODEL]
    assert len(mine) == 1  # latest per (model, prompt_version)
    assert mine[0]["accuracy"]["guidance_direction"] == 0.5
    assert mine[0]["labellers"] == ["tester"]
    assert mine[0]["confusion"]["guidance_direction"]["lowered"] == {"raised": 1}
    all_runs = TestClient(create_app()).get("/evals", params={"latest_only": False}).json()
    assert len([r for r in all_runs if r["model"] == MODEL]) == 2


def test_gold_records_missing_from_db_are_an_error(
    db: tuple[Session, Path, Path], tmp_path: Path
) -> None:
    session, data_dir, _ = db
    bad = tmp_path / "bad.jsonl"
    bad.write_text(
        (db[2]).read_text(encoding="utf-8").replace("zzeval-1", "not-in-db"), encoding="utf-8"
    )
    with pytest.raises(GoldSetError, match="not-in-db"):
        run_eval(session=session, **_kwargs(Scripted(), data_dir, bad))


def test_empty_gold_set_is_an_error(db: tuple[Session, Path, Path], tmp_path: Path) -> None:
    session, data_dir, _ = db
    with pytest.raises(GoldSetError, match="eval label"):
        run_eval(session=session, **_kwargs(Scripted(), data_dir, tmp_path / "none.jsonl"))
