"""Gold file, labelling flow, scoring maths and the regression check (no DB, no network)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from newsalpha.eval.gold import GoldLabels, GoldRecord, append_gold, load_gold
from newsalpha.eval.labelling import QuitLabelling, SkipDocument, ask_labels, labelling_order
from newsalpha.eval.regress import SubsetDoc, compare, load_subset, score_subset, write_baseline
from newsalpha.eval.scoring import FAILED, Prediction, score
from newsalpha.extraction.models_config import ExtractionSettings, ModelPrice
from newsalpha.extraction.prompts import load_prompt
from newsalpha.extraction.providers import LLMResponse

BACKEND = Path(__file__).resolve().parents[1]
VALID: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "llm" / "valid_signals.json").read_text()
)


def labels(g: str, rev: str, eps: str, tone: float) -> GoldLabels:
    return GoldLabels.model_validate(
        {
            "guidance_direction": g,
            "revenue_vs_expectation": rev,
            "eps_vs_expectation": eps,
            "management_tone": tone,
        }
    )


def payload(g: str, rev: str, eps: str, tone: float) -> dict[str, Any]:
    return VALID | {
        "guidance_direction": g,
        "revenue_vs_expectation": rev,
        "eps_vs_expectation": eps,
        "management_tone": tone,
    }


def record(sid: str, lab: GoldLabels) -> GoldRecord:
    return GoldRecord(
        source="edgar",
        source_id=sid,
        ticker="EXCO",
        labels=lab,
        labeller="tester",
        labelled_at=datetime(2026, 9, 29, tzinfo=UTC),
    )


# ------------------------------------------------------------------ scoring (hand-computed)


def test_score_hand_computed_example() -> None:
    gold = [
        labels("raised", "beat", "unknown", 0.5),
        labels("lowered", "unknown", "miss", -0.5),
        labels("not_mentioned", "unknown", "unknown", 0.0),
        labels("maintained", "inline", "unknown", 0.2),
    ]
    preds = [
        Prediction(payload("raised", "beat", "unknown", 0.7), 0.002, 1000),  # all right
        Prediction(payload("lowered", "unknown", "unknown", -0.1), 0.004, 3000),  # eps wrong
        Prediction(None, 0.001, 2000),  # failed: every field counts as wrong
        Prediction(payload("raised", "inline", "unknown", 0.2), 0.0, 0, cache_hit=True),
    ]
    m = score(gold, preds)
    assert m["n_gold"] == 4 and m["n_ok"] == 3
    assert m["schema_failure_rate"] == 0.25
    assert m["fields"]["guidance_direction"]["accuracy"] == pytest.approx(2 / 4)
    assert m["fields"]["revenue_vs_expectation"]["accuracy"] == pytest.approx(3 / 4)
    assert m["fields"]["eps_vs_expectation"]["accuracy"] == pytest.approx(2 / 4)
    assert m["mean_accuracy"] == pytest.approx((2 / 4 + 3 / 4 + 2 / 4) / 3)
    # Most common gold label: guidance has 4 distinct labels (1/4); eps "unknown" 3 of 4.
    assert m["fields"]["guidance_direction"]["majority_baseline"] == pytest.approx(1 / 4)
    assert m["fields"]["eps_vs_expectation"]["majority_baseline"] == pytest.approx(3 / 4)
    # Tone MAE over the 3 successful docs: |0.2| + |0.4| + |0.0| = 0.6 / 3
    assert m["management_tone_mae"] == pytest.approx(0.2)
    # Cost/latency ignore the cache hit: (0.002 + 0.004 + 0.001) / 3
    assert m["mean_cost_per_doc_usd"] == pytest.approx(0.007 / 3)
    assert m["latency_p50_ms"] == 2000.0 and m["latency_p95_ms"] == 3000.0
    confusion = m["fields"]["guidance_direction"]["confusion"]
    assert confusion["not_mentioned"] == {FAILED: 1}
    assert confusion["maintained"] == {"raised": 1}


def test_score_rejects_misaligned_inputs() -> None:
    with pytest.raises(ValueError, match="aligned"):
        score([labels("raised", "beat", "beat", 0)], [])


def test_regression_gate() -> None:
    base = {"mean_accuracy": 0.80, "schema_failure_rate": 0.0}
    assert compare(base, {"mean_accuracy": 0.72, "schema_failure_rate": 0.05}, 0.10) == []
    problems = compare(base, {"mean_accuracy": 0.65, "schema_failure_rate": 0.15}, 0.10)
    assert len(problems) == 2


# ------------------------------------------------------------------ gold file and labelling


def test_gold_round_trip_and_duplicate_detection(tmp_path: Path) -> None:
    path = tmp_path / "gold.jsonl"
    assert load_gold(path) == []
    rec = record("0001-24-000001", labels("raised", "beat", "unknown", 0.4))
    append_gold(rec, path)
    assert load_gold(path) == [rec]
    append_gold(rec, path)
    with pytest.raises(ValueError, match="duplicate"):
        load_gold(path)


def test_invalid_gold_line_reports_its_line_number(tmp_path: Path) -> None:
    path = tmp_path / "gold.jsonl"
    path.write_text('{"source": "edgar"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"gold.jsonl:1"):
        load_gold(path)


def test_labelling_order_is_reproducible_and_independent_of_input_order() -> None:
    ids = [f"id-{i}" for i in range(50)]
    assert labelling_order(ids) == labelling_order(list(reversed(ids)))
    assert labelling_order(ids) != sorted(ids)


def _asker(answers: list[str]):  # type: ignore[no-untyped-def]
    it = iter(answers)
    return lambda _q: next(it)


def test_ask_labels_accepts_keys_and_full_names_and_reprompts_on_bad_input() -> None:
    got = ask_labels(_asker(["x", "r", "beat", "u", "2", "abc", "0.25"]))
    assert got == labels("raised", "beat", "unknown", 0.25)


def test_ask_labels_skip_and_quit() -> None:
    with pytest.raises(SkipDocument):
        ask_labels(_asker(["s"]))
    with pytest.raises(QuitLabelling):
        ask_labels(_asker(["r", "b", "q"]))


# ------------------------------------------------------------------ regression check


class Scripted:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = list(payloads)

    def complete(self, **_kw: Any) -> LLMResponse:
        return LLMResponse(json.dumps(self.payloads.pop(0)), 100, 0, 20, 50)


def test_baseline_freeze_and_rescore(tmp_path: Path) -> None:
    gold = [
        record("a", labels("raised", "beat", "unknown", 0.5)),
        record("b", labels("lowered", "unknown", "miss", -0.3)),
    ]
    docs = [SubsetDoc(gold[0], "Example Co", "text A"), SubsetDoc(gold[1], "Other Co", "text B")]
    kwargs: dict[str, Any] = {
        "model": "fake",
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
        "sleep": lambda _s: None,
    }
    metrics = score_subset(
        docs,
        provider=Scripted(
            [payload("raised", "beat", "unknown", 0.5), payload("lowered", "unknown", "miss", -0.3)]
        ),
        **kwargs,
    )
    assert metrics["mean_accuracy"] == 1.0

    baseline_path, texts = tmp_path / "baseline.json", tmp_path / "texts"
    write_baseline(docs, metrics, "fake", kwargs["prompt"], 0.1, baseline_path, texts)
    baseline = json.loads(baseline_path.read_text())
    reloaded = load_subset(baseline, gold, texts)
    assert [d.text for d in reloaded] == ["text A", "text B"]
    assert reloaded[1].company_name == "Other Co"

    worse = score_subset(
        reloaded,
        provider=Scripted(
            [
                payload("maintained", "inline", "beat", 0.0),
                payload("lowered", "unknown", "miss", -0.3),
            ]
        ),
        **kwargs,
    )
    assert compare(baseline["metrics"], worse, baseline["threshold"])  # regression detected
