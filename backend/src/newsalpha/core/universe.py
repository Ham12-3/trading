"""Study universe loaded from ``config/universe.yaml``."""

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class UniverseMember:
    ticker: str
    name: str
    sector: str


@dataclass(frozen=True)
class Universe:
    as_of: str
    source: str
    benchmark: str
    companies: tuple[UniverseMember, ...]

    @property
    def tickers(self) -> list[str]:
        return [c.ticker for c in self.companies]


def load_universe(path: Path) -> Universe:
    """Parse and validate the universe file (unique tickers, benchmark present)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    members = tuple(
        UniverseMember(ticker=str(c["ticker"]), name=str(c["name"]), sector=str(c["sector"]))
        for c in raw["companies"]
    )
    tickers = [m.ticker for m in members]
    dupes = sorted({t for t in tickers if tickers.count(t) > 1})
    if dupes:
        raise ValueError(f"duplicate tickers in {path}: {dupes}")
    return Universe(
        as_of=str(raw["as_of"]),
        source=str(raw["source"]),
        benchmark=str(raw["benchmark"]),
        companies=members,
    )
