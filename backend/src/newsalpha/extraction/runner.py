"""Batch extraction: pick pending announcements, reuse cached results, call the LLM in parallel,
and store one ``signals`` row per (announcement, model, prompt_version)."""

import logging
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from newsalpha.db.models import Announcement, Company, Signal
from newsalpha.extraction.extract import ExtractionOutcome, extract_document
from newsalpha.extraction.models_config import ExtractionSettings, ModelPrice
from newsalpha.extraction.prompts import Prompt
from newsalpha.extraction.providers import LLMProvider

log = logging.getLogger(__name__)


class PromptChangedError(RuntimeError):
    """The prompt file changed but its version did not; results would be mixed."""


@dataclass
class RunReport:
    documents: int = 0
    ok: int = 0
    failed: int = 0
    cache_hits: int = 0
    truncated: int = 0
    cost_usd: float = 0.0
    latencies_ms: list[int] = field(default_factory=list)

    @property
    def failure_rate(self) -> float:
        return self.failed / self.documents if self.documents else 0.0


@dataclass(frozen=True)
class _Pending:
    announcement_id: int
    text_hash: str
    raw_text_uri: str
    company_name: str


def check_prompt_unchanged(session: Session, model: str, prompt: Prompt) -> None:
    """Refuse to extend a (model, version) run with an edited prompt file."""
    seen = set(
        session.scalars(
            select(Signal.prompt_sha256)
            .where(Signal.model == model, Signal.prompt_version == prompt.version)
            .distinct()
        )
    )
    if seen - {prompt.sha256}:
        raise PromptChangedError(
            f"prompts/extract_{prompt.version}.md changed since earlier {model} runs; "
            "bump the prompt version instead of editing it in place"
        )


def select_pending(
    session: Session,
    model: str,
    version: str,
    limit: int | None,
    retry_failed: bool,
    announcement_ids: list[int] | None = None,
) -> list[_Pending]:
    """Announcements without an ok signal for (model, version), oldest first.

    ``announcement_ids`` restricts the candidates (used by evaluation on the gold set)."""
    done_status = ["ok"] if retry_failed else ["ok", "failed"]
    done = (
        select(Signal.announcement_id)
        .where(
            Signal.model == model,
            Signal.prompt_version == version,
            Signal.status.in_(done_status),
        )
        .scalar_subquery()
    )
    stmt = (
        select(Announcement.id, Announcement.text_hash, Announcement.raw_text_uri, Company.name)
        .join(Company, Company.id == Announcement.company_id)
        .where(Announcement.id.not_in(done))
        .where(Announcement.id.in_(announcement_ids) if announcement_ids is not None else true())
        .order_by(Announcement.accepted_at, Announcement.id)
        .limit(limit)
    )
    return [_Pending(*row) for row in session.execute(stmt)]


def _cached_payloads(
    session: Session, model: str, version: str, hashes: set[str]
) -> dict[str, dict[str, Any] | None]:
    rows = session.execute(
        select(Signal.document_hash, Signal.payload).where(
            Signal.model == model,
            Signal.prompt_version == version,
            Signal.status == "ok",
            Signal.document_hash.in_(hashes),
        )
    )
    return {h: p for h, p in rows}


def _write(
    session: Session,
    pending: _Pending,
    model: str,
    prompt: Prompt,
    outcome: ExtractionOutcome,
    cache_hit: bool,
) -> None:
    values = {
        "announcement_id": pending.announcement_id,
        "model": model,
        "prompt_version": prompt.version,
        "prompt_sha256": prompt.sha256,
        "document_hash": pending.text_hash,
        "status": outcome.status,
        "payload": outcome.payload,
        "error": outcome.error,
        "attempts": 0 if cache_hit else outcome.attempts,
        "truncated": outcome.truncated,
        "cache_hit": cache_hit,
        "input_tokens": 0 if cache_hit else outcome.input_tokens,
        "cached_input_tokens": 0 if cache_hit else outcome.cached_input_tokens,
        "output_tokens": 0 if cache_hit else outcome.output_tokens,
        "cost_usd": 0.0 if cache_hit else outcome.cost_usd,
        "latency_ms": 0 if cache_hit else outcome.latency_ms,
    }
    stmt = insert(Signal).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Signal.announcement_id, Signal.model, Signal.prompt_version],
        set_={k: stmt.excluded[k] for k in values if k not in ("announcement_id", "model")},
    )
    session.execute(stmt)
    session.commit()


def _record(report: RunReport, outcome: ExtractionOutcome, cache_hit: bool) -> None:
    report.documents += 1
    report.ok += outcome.status == "ok"
    report.failed += outcome.status == "failed"
    report.truncated += outcome.truncated
    if cache_hit:
        report.cache_hits += 1
        return
    report.cost_usd += outcome.cost_usd
    report.latencies_ms.append(outcome.latency_ms)


def run_extraction(
    *,
    session: Session,
    provider: LLMProvider,
    model: str,
    prompt: Prompt,
    price: ModelPrice,
    settings: ExtractionSettings,
    data_dir: Path,
    limit: int | None = None,
    retry_failed: bool = False,
    announcement_ids: list[int] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> RunReport:
    """Extract signals for pending announcements. Each document is paid for at most once per
    (text hash, model, prompt version)."""
    check_prompt_unchanged(session, model, prompt)
    pending = select_pending(session, model, prompt.version, limit, retry_failed, announcement_ids)
    report = RunReport()
    if not pending:
        return report

    by_hash: dict[str, list[_Pending]] = defaultdict(list)
    for p in pending:
        by_hash[p.text_hash].append(p)
    cached = _cached_payloads(session, model, prompt.version, set(by_hash))

    for text_hash in list(by_hash):
        if text_hash in cached:
            hit = ExtractionOutcome(status="ok", payload=cached[text_hash])
            for p in by_hash.pop(text_hash):
                _write(session, p, model, prompt, hit, cache_hit=True)
                _record(report, hit, cache_hit=True)

    def work(group: list[_Pending]) -> ExtractionOutcome:
        first = group[0]
        path = data_dir / first.raw_text_uri
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return ExtractionOutcome(error=f"cannot read {path}: {exc}")
        return extract_document(
            provider=provider,
            model=model,
            prompt=prompt,
            company_name=first.company_name,
            text=text,
            settings=settings,
            price=price,
            sleep=sleep,
        )

    with ThreadPoolExecutor(max_workers=settings.concurrency) as pool:
        futures = {pool.submit(work, group): group for group in by_hash.values()}
        for future in as_completed(futures):
            group = futures[future]
            outcome = future.result()
            # The first document in a group paid for the call; identical texts reuse it.
            for i, p in enumerate(group):
                _write(session, p, model, prompt, outcome, cache_hit=i > 0)
                _record(report, outcome, cache_hit=i > 0)
            if outcome.status == "failed":
                log.warning("announcement %d failed: %s", group[0].announcement_id, outcome.error)
            else:
                log.info("announcement %d ok", group[0].announcement_id)
    return report
