"""Score a (model, prompt_version) on the gold set and store the result as an ``eval_runs`` row."""

import time
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsalpha.db.models import Announcement, EvalRun, Signal
from newsalpha.eval.gold import GoldRecord, gold_sha256, load_gold
from newsalpha.eval.scoring import Prediction, score
from newsalpha.extraction.models_config import ExtractionSettings, ModelPrice
from newsalpha.extraction.prompts import Prompt
from newsalpha.extraction.providers import LLMProvider
from newsalpha.extraction.runner import run_extraction


class GoldSetError(RuntimeError):
    """The gold set is empty or refers to announcements that are not in the database."""


def resolve_gold(session: Session, gold: list[GoldRecord]) -> list[int]:
    """Announcement ids for the gold records, in gold order."""
    keys = {(g.source, g.source_id) for g in gold}
    rows = session.execute(
        select(Announcement.source, Announcement.source_id, Announcement.id).where(
            Announcement.source_id.in_([k[1] for k in keys])
        )
    ).all()
    found = {(src, sid): aid for src, sid, aid in rows}
    missing = sorted(k[1] for k in keys if k not in found)
    if missing:
        raise GoldSetError(f"gold records not found in announcements: {missing[:10]}")
    return [found[(g.source, g.source_id)] for g in gold]


def load_predictions(
    session: Session, model: str, version: str, announcement_ids: list[int]
) -> list[Prediction]:
    """Stored signals aligned with ``announcement_ids``; a missing row counts as a failure."""
    rows = {
        s.announcement_id: s
        for s in session.scalars(
            select(Signal).where(
                Signal.model == model,
                Signal.prompt_version == version,
                Signal.announcement_id.in_(announcement_ids),
            )
        )
    }
    out = []
    for aid in announcement_ids:
        s = rows.get(aid)
        if s is None:
            out.append(Prediction(payload=None, cost_usd=0.0, latency_ms=0, cache_hit=True))
        else:
            out.append(
                Prediction(
                    payload=s.payload if s.status == "ok" else None,
                    cost_usd=s.cost_usd,
                    latency_ms=s.latency_ms,
                    cache_hit=s.cache_hit,
                )
            )
    return out


def run_eval(
    *,
    session: Session,
    provider: LLMProvider,
    model: str,
    prompt: Prompt,
    price: ModelPrice,
    settings: ExtractionSettings,
    data_dir: Path,
    gold_path: Path,
    sleep: Callable[[float], None] = time.sleep,
) -> EvalRun:
    """Extract any gold documents not yet done for (model, prompt), score, and store the run."""
    gold = load_gold(gold_path)
    if not gold:
        raise GoldSetError(f"no gold labels in {gold_path}; run `newsalpha eval label` first")
    ids = resolve_gold(session, gold)
    run_extraction(
        session=session,
        provider=provider,
        model=model,
        prompt=prompt,
        price=price,
        settings=settings,
        data_dir=data_dir,
        announcement_ids=ids,
        sleep=sleep,
    )
    metrics = score([g.labels for g in gold], load_predictions(session, model, prompt.version, ids))
    run = EvalRun(
        model=model,
        prompt_version=prompt.version,
        n_gold=len(gold),
        gold_sha256=gold_sha256(gold_path),
        metrics=metrics,
    )
    session.add(run)
    session.commit()
    return run
