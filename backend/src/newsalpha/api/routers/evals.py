"""Model comparison table from stored eval runs."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from newsalpha.db.models import EvalRun
from newsalpha.db.session import get_session

router = APIRouter(tags=["evals"])


class EvalRunOut(BaseModel):
    id: int
    model: str
    prompt_version: str
    n_gold: int
    gold_sha256: str
    created_at: datetime
    mean_accuracy: float
    accuracy: dict[str, float]  # per categorical field
    management_tone_mae: float | None
    schema_failure_rate: float
    mean_cost_per_doc_usd: float | None
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    confusion: dict[str, dict[str, dict[str, int]]]  # field -> gold label -> predicted -> count

    @classmethod
    def from_row(cls, run: EvalRun) -> "EvalRunOut":
        m: dict[str, Any] = run.metrics
        return cls(
            id=run.id,
            model=run.model,
            prompt_version=run.prompt_version,
            n_gold=run.n_gold,
            gold_sha256=run.gold_sha256,
            created_at=run.created_at,
            mean_accuracy=m["mean_accuracy"],
            accuracy={name: f["accuracy"] for name, f in m["fields"].items()},
            management_tone_mae=m["management_tone_mae"],
            schema_failure_rate=m["schema_failure_rate"],
            mean_cost_per_doc_usd=m["mean_cost_per_doc_usd"],
            latency_p50_ms=m["latency_p50_ms"],
            latency_p95_ms=m["latency_p95_ms"],
            confusion={name: f["confusion"] for name, f in m["fields"].items()},
        )


@router.get("/evals", response_model=list[EvalRunOut])
def list_evals(
    session: Annotated[Session, Depends(get_session)], latest_only: bool = True
) -> list[EvalRunOut]:
    """Eval runs, newest first. ``latest_only`` keeps the newest run per (model, prompt_version)."""
    runs = session.scalars(select(EvalRun).order_by(EvalRun.created_at.desc(), EvalRun.id.desc()))
    out: list[EvalRunOut] = []
    seen: set[tuple[str, str]] = set()
    for run in runs:
        key = (run.model, run.prompt_version)
        if latest_only and key in seen:
            continue
        seen.add(key)
        out.append(EvalRunOut.from_row(run))
    return out
