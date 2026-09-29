"""Score model extractions against gold labels. Pure functions, no I/O."""

from dataclasses import dataclass
from typing import Any

from newsalpha.core.stats import percentile
from newsalpha.eval.gold import SCORED_FIELDS, GoldLabels

FAILED = "__failed__"  # prediction placeholder when the extraction failed schema validation


@dataclass(frozen=True)
class Prediction:
    """One model output for one gold document; ``payload`` is None if extraction failed."""

    payload: dict[str, Any] | None
    cost_usd: float
    latency_ms: int
    cache_hit: bool = False


def score(gold: list[GoldLabels], predictions: list[Prediction]) -> dict[str, Any]:
    """Metrics for one (model, prompt_version) over the gold set.

    Categorical accuracy is over *all* gold documents: a failed extraction counts as wrong, so
    a model cannot look better by failing on hard documents. Tone MAE is over successful ones.
    """
    if len(gold) != len(predictions):
        raise ValueError("gold and predictions must be aligned")
    n = len(gold)
    ok = [p.payload is not None for p in predictions]
    fields: dict[str, Any] = {}
    for name in SCORED_FIELDS:
        confusion: dict[str, dict[str, int]] = {}
        correct = 0
        for g, p in zip(gold, predictions, strict=True):
            truth = str(getattr(g, name))  # StrEnum and Literal values both stringify to the label
            pred = str(p.payload[name]) if p.payload is not None else FAILED
            correct += truth == pred
            row = confusion.setdefault(truth, {})
            row[pred] = row.get(pred, 0) + 1
        # Accuracy of always answering the most common gold label: the bar a model must clear
        # for its accuracy on this field to mean anything.
        majority = max((sum(r.values()) for r in confusion.values()), default=0)
        fields[name] = {
            "accuracy": correct / n if n else 0.0,
            "majority_baseline": majority / n if n else 0.0,
            "confusion": confusion,
        }

    tone_errors = [
        abs(float(p.payload["management_tone"]) - g.management_tone)
        for g, p in zip(gold, predictions, strict=True)
        if p.payload is not None
    ]
    paid = [p for p in predictions if not p.cache_hit]
    return {
        "n_gold": n,
        "n_ok": sum(ok),
        "schema_failure_rate": (n - sum(ok)) / n if n else 0.0,
        "fields": fields,
        "mean_accuracy": (
            sum(f["accuracy"] for f in fields.values()) / len(fields) if fields else 0.0
        ),
        "management_tone_mae": sum(tone_errors) / len(tone_errors) if tone_errors else None,
        "mean_cost_per_doc_usd": sum(p.cost_usd for p in paid) / len(paid) if paid else None,
        "latency_p50_ms": percentile([p.latency_ms for p in paid], 50) if paid else None,
        "latency_p95_ms": percentile([p.latency_ms for p in paid], 95) if paid else None,
    }
