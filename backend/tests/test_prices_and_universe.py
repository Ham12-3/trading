"""yfinance bar normalisation and the universe file (no network)."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from newsalpha.core.universe import load_universe
from newsalpha.sources.base import SourceError
from newsalpha.sources.yahoo import normalise_bars, yahoo_symbol

UNIVERSE = Path(__file__).resolve().parents[1] / "config" / "universe.yaml"


def _raw() -> pd.DataFrame:
    idx = pd.DatetimeIndex(["2024-01-22 00:00:00-05:00", "2024-01-23 00:00:00-05:00"], name="Date")
    return pd.DataFrame(
        {
            "Open": [100.0, 110.0],
            "High": [105.0, 112.0],
            "Low": [99.0, 108.0],
            "Close": [104.0, 111.0],
            "Adj Close": [52.0, 55.5],  # factor 0.5 (e.g. after a later 2:1 split)
            "Volume": [1000, 2000],
        },
        index=idx,
    )


def test_adj_open_uses_the_close_adjustment_factor() -> None:
    bars = normalise_bars(_raw(), "EXCO")
    assert list(bars.columns) == ["open", "high", "low", "close", "adj_close", "adj_open", "volume"]
    assert bars["adj_open"].tolist() == pytest.approx([50.0, 55.0])
    assert pd.DatetimeIndex(bars.index).tz is None
    assert [d.isoformat() for d in pd.DatetimeIndex(bars.index).date] == [
        "2024-01-22",
        "2024-01-23",
    ]


def test_missing_columns_are_an_error() -> None:
    with pytest.raises(SourceError, match="missing columns"):
        normalise_bars(_raw().drop(columns=["Adj Close"]), "EXCO")


def test_yahoo_share_class_spelling() -> None:
    assert yahoo_symbol("BRK.B") == "BRK-B"


def test_universe_file() -> None:
    universe = load_universe(UNIVERSE)
    assert len(universe.companies) == 100
    assert universe.benchmark == "SPY"
    assert universe.as_of < "2024-01-01"  # chosen before the study window
    assert "GOOGL" in universe.tickers and "GOOG" not in universe.tickers


def test_yahoo_source_retries_then_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    from newsalpha.sources.yahoo import YahooPriceSource

    monkeypatch.setattr(time, "sleep", lambda _s: None)
    source = YahooPriceSource(max_retries=2)
    outcomes: list[object] = [RuntimeError("throttled"), _raw()]
    monkeypatch.setattr(source, "_download", lambda *_a: _pop(outcomes))
    bars = source.fetch_daily("EXCO", date(2024, 1, 22), date(2024, 1, 23))
    assert len(bars) == 2

    monkeypatch.setattr(source, "_download", lambda *_a: _pop([RuntimeError("down")] * 3))
    with pytest.raises(SourceError, match="after 3 attempts"):
        source.fetch_daily("EXCO", date(2024, 1, 22), date(2024, 1, 23))


def _pop(outcomes: list[object]) -> pd.DataFrame:
    item = outcomes.pop(0)
    if isinstance(item, Exception):
        raise item
    assert isinstance(item, pd.DataFrame)
    return item


def test_renamed_ticker_is_looked_up_by_current_symbol() -> None:
    bk = next(m for m in load_universe(UNIVERSE).companies if m.ticker == "BK")
    assert bk.lookup_ticker == "BNY"
