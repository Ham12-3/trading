"""Study universe loaded from ``config/universe.yaml``."""

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class UniverseMember:
    ticker: str  # symbol at the universe snapshot date; the key used everywhere downstream
    name: str
    sector: str
    current_ticker: str | None = None  # set when the listing symbol changed later (BK -> BNY)

    @property
    def lookup_ticker(self) -> str:
        """Symbol to query today's data sources with."""
        return self.current_ticker or self.ticker


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
        UniverseMember(
            ticker=str(c["ticker"]),
            name=str(c["name"]),
            sector=str(c["sector"]),
            current_ticker=str(c["current_ticker"]) if c.get("current_ticker") else None,
        )
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
