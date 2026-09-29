"""Interactive gold labelling. The model's own output is never shown, to avoid anchoring."""

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from newsalpha.eval.gold import GoldLabels

LABEL_SEED = 20240101  # fixed so the labelling order (and so the gold sample) is reproducible
SKIPPED_PATH = Path("../eval/gold/skipped.txt")

GUIDANCE_KEYS = {
    "r": "raised",
    "m": "maintained",
    "l": "lowered",
    "w": "withdrawn",
    "n": "not_mentioned",
}
EXPECTATION_KEYS = {"b": "beat", "i": "inline", "m": "miss", "u": "unknown"}


class SkipDocument(Exception):  # noqa: N818  (control flow, not an error)
    """The labeller chose to skip this document."""


class QuitLabelling(Exception):  # noqa: N818
    """The labeller chose to stop the session."""


@dataclass(frozen=True)
class Candidate:
    source: str
    source_id: str
    ticker: str
    company_name: str
    accepted_at: datetime
    url: str
    text_path: Path


def labelling_order(source_ids: list[str], seed: int = LABEL_SEED) -> list[str]:
    """A fixed pseudo-random order over all announcements (independent of database ids)."""
    ordered = sorted(source_ids)
    random.Random(seed).shuffle(ordered)
    return ordered


def load_skipped(path: Path = SKIPPED_PATH) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def record_skip(source_id: str, path: Path = SKIPPED_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(source_id + "\n")


def _choice(ask: Callable[[str], str], question: str, keys: dict[str, str]) -> str:
    options = "  ".join(f"[{k}] {v}" for k, v in keys.items())
    while True:
        answer = ask(f"{question}\n  {options}  [s] skip  [q] quit\n> ").strip().lower()
        if answer == "s":
            raise SkipDocument
        if answer == "q":
            raise QuitLabelling
        if answer in keys:
            return keys[answer]
        if answer in keys.values():
            return answer


def _tone(ask: Callable[[str], str]) -> float:
    while True:
        answer = (
            ask(
                "Management tone, -1 (very negative) .. 0 (neutral) .. 1 (very positive)"
                "  [s] skip  [q] quit\n> "
            )
            .strip()
            .lower()
        )
        if answer == "s":
            raise SkipDocument
        if answer == "q":
            raise QuitLabelling
        try:
            value = float(answer)
        except ValueError:
            continue
        if -1.0 <= value <= 1.0:
            return value


def ask_labels(ask: Callable[[str], str]) -> GoldLabels:
    """Ask for each scored field. Raises ``SkipDocument`` or ``QuitLabelling`` on request."""
    guidance = _choice(
        ask, "Guidance direction (vs the company's previous outlook)?", GUIDANCE_KEYS
    )
    revenue = _choice(
        ask, "Revenue vs expectations/guidance, as stated in the text?", EXPECTATION_KEYS
    )
    eps = _choice(ask, "EPS vs expectations/guidance, as stated in the text?", EXPECTATION_KEYS)
    tone = _tone(ask)
    return GoldLabels.model_validate(
        {
            "guidance_direction": guidance,
            "revenue_vs_expectation": revenue,
            "eps_vs_expectation": eps,
            "management_tone": tone,
        }
    )
