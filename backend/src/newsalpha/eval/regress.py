"""Accuracy regression check on a small, fixed slice of the gold set (PRD section 9.5).

The slice's announcement texts are frozen into ``eval/gold/texts/`` (public SEC filings), so the
check runs in CI without the database. ``eval/baseline.json`` holds the reference scores.
LLM output is not perfectly deterministic: on 20 documents one flipped label moves a field's
accuracy by 5 points, so the default threshold (10 points of mean accuracy) allows for that.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from newsalpha.eval.gold import GoldRecord
from newsalpha.eval.scoring import Prediction, score
from newsalpha.extraction.extract import extract_document
from newsalpha.extraction.models_config import ExtractionSettings, ModelPrice
from newsalpha.extraction.prompts import Prompt
from newsalpha.extraction.providers import LLMProvider

BASELINE_PATH = Path("../eval/baseline.json")
TEXTS_DIR = Path("../eval/gold/texts")
DEFAULT_SUBSET = 20
DEFAULT_THRESHOLD = 0.10


@dataclass(frozen=True)
class SubsetDoc:
    record: GoldRecord
    company_name: str
    text: str


def score_subset(
    docs: list[SubsetDoc],
    *,
    provider: LLMProvider,
    model: str,
    prompt: Prompt,
    price: ModelPrice,
    settings: ExtractionSettings,
    sleep: Callable[[float], None],
) -> dict[str, Any]:
    """Run the model live on each document (no database) and score against gold."""
    preds = []
    for doc in docs:
        out = extract_document(
            provider=provider,
            model=model,
            prompt=prompt,
            company_name=doc.company_name,
            text=doc.text,
            settings=settings,
            price=price,
            sleep=sleep,
        )
        preds.append(Prediction(out.payload, out.cost_usd, out.latency_ms))
    return score([d.record.labels for d in docs], preds)


def write_baseline(
    docs: list[SubsetDoc],
    metrics: dict[str, Any],
    model: str,
    prompt: Prompt,
    threshold: float,
    path: Path = BASELINE_PATH,
    texts_dir: Path = TEXTS_DIR,
) -> None:
    """Freeze the subset texts and the reference scores."""
    texts_dir.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        (texts_dir / f"{doc.record.source_id}.txt").write_text(
            doc.text, encoding="utf-8", newline="\n"
        )
    baseline = {
        "model": model,
        "prompt_version": prompt.version,
        "prompt_sha256": prompt.sha256,
        "threshold": threshold,
        "subset": [
            {
                "source": d.record.source,
                "source_id": d.record.source_id,
                "company_name": d.company_name,
            }
            for d in docs
        ],
        "metrics": metrics,
    }
    path.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8", newline="\n")


def load_subset(
    baseline: dict[str, Any], gold: list[GoldRecord], texts_dir: Path = TEXTS_DIR
) -> list[SubsetDoc]:
    by_id = {(g.source, g.source_id): g for g in gold}
    docs = []
    for item in baseline["subset"]:
        record = by_id.get((item["source"], item["source_id"]))
        if record is None:
            raise ValueError(f"baseline document {item['source_id']} is no longer in the gold set")
        text = (texts_dir / f"{item['source_id']}.txt").read_text(encoding="utf-8")
        docs.append(SubsetDoc(record, item["company_name"], text))
    return docs


def compare(baseline: dict[str, Any], current: dict[str, Any], threshold: float) -> list[str]:
    """Regressions as readable strings (empty list means pass).

    Fails when mean categorical accuracy drops, or the schema failure rate rises, by more than
    ``threshold``. Per-field accuracy is reported but not gated: on a 20-document slice a single
    label is 5 points, which would make a per-field gate flaky.
    """
    problems = []
    b_mean, c_mean = baseline["mean_accuracy"], current["mean_accuracy"]
    if b_mean - c_mean > threshold:
        problems.append(f"mean accuracy {c_mean:.1%} vs baseline {b_mean:.1%}")
    b_fail, c_fail = baseline["schema_failure_rate"], current["schema_failure_rate"]
    if c_fail - b_fail > threshold:
        problems.append(f"schema failure rate {c_fail:.1%} vs baseline {b_fail:.1%}")
    return problems
