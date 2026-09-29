"""Hand-labelled gold set: ``eval/gold/*.jsonl``, one JSON object per labelled announcement.

Records are keyed by the source's own id (EDGAR accession number), not a database id, so the
gold set survives a database rebuild.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from newsalpha.extraction.schema import Expectation, GuidanceDirection

GOLD_PATH = Path("../eval/gold/gold.jsonl")
SCORED_FIELDS = ("guidance_direction", "revenue_vs_expectation", "eps_vs_expectation")


class GoldLabels(BaseModel):
    """The subset of ``AnnouncementSignals`` a human labels and the eval scores."""

    model_config = ConfigDict(extra="forbid")

    guidance_direction: GuidanceDirection
    revenue_vs_expectation: Expectation
    eps_vs_expectation: Expectation
    management_tone: float = Field(ge=-1.0, le=1.0)


class GoldRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    source_id: str
    ticker: str
    labels: GoldLabels
    labeller: str
    labelled_at: datetime
    notes: str = ""


def load_gold(path: Path = GOLD_PATH) -> list[GoldRecord]:
    """All records in file order; a missing file is an empty gold set. Duplicates are an error."""
    if not path.exists():
        return []
    records = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                records.append(GoldRecord.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(f"{path}:{n}: invalid gold record: {exc}") from exc
    keys = [(r.source, r.source_id) for r in records]
    dupes = sorted({k[1] for k in keys if keys.count(k) > 1})
    if dupes:
        raise ValueError(f"{path}: duplicate gold records for {dupes}")
    return records


def append_gold(record: GoldRecord, path: Path = GOLD_PATH) -> None:
    """Append one record and flush immediately, so a labelling session can stop at any time."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")


def gold_sha256(path: Path = GOLD_PATH) -> str:
    """Fingerprint of the gold file, stored with each eval run."""
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""
