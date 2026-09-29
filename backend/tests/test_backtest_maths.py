"""Event construction, event-study stats, metrics, strategies and portfolio P&L on hand-computed
examples (no DB). Dates use the real NYSE calendar."""

import math
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from newsalpha.backtest.config import PortfolioConfig, Weights
from newsalpha.backtest.event_study import event_study, mean_t
from newsalpha.backtest.events import compute_event
from newsalpha.backtest.metrics import (
    annualised_return,
    max_drawdown,
    sharpe_ratio,
)
from newsalpha.backtest.portfolio import Trade, simulate
from newsalpha.backtest.strategy import (
    beat_miss_sides,
    composite_score,
    gap_sides,
    threshold_sides,
)
from newsalpha.core.calendar import TradingCalendar, get_calendar

ET = ZoneInfo("America/New_York")


@pytest.fixture(scope="module")
def cal() -> TradingCalendar:
    return get_calendar()


def bars(rows: dict[str, tuple[float, float]]) -> pd.DataFrame:
    """{date: (adj_open, adj_close)} -> bar frame indexed by Timestamp."""
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in rows], name="date")
    return pd.DataFrame(
        {"adj_open": [o for o, _ in rows.values()], "adj_close": [c for _, c in rows.values()]},
        index=idx,
    )


# ------------------------------------------------------------------ events

STOCK = {
    "2024-01-23": (99.0, 100.0),  # day before t0: prev close 100
    "2024-01-24": (102.0, 104.0),  # t0: entry at the 102 open (gap +2%)
    "2024-01-25": (104.0, 107.1),  # t0+1
    "2024-01-26": (107.0, 105.06),
    "2024-01-29": (105.0, 110.16),  # t0+3
}
BENCH = {
    "2024-01-23": (399.0, 400.0),
    "2024-01-24": (404.0, 404.0),  # bench gap +1%
    "2024-01-25": (404.0, 408.04),
    "2024-01-26": (408.0, 404.0),
    "2024-01-29": (404.0, 412.08),
}


def test_event_entry_gap_and_abnormal_returns(cal: TradingCalendar) -> None:
    accepted = datetime(2024, 1, 23, 16, 5, tzinfo=ET)  # after close -> t0 Wed 2024-01-24
    ev = compute_event(accepted, bars(STOCK), bars(BENCH), cal)
    assert ev.t0 == date(2024, 1, 24)
    assert ev.entry_price == 102.0 and ev.bench_entry_price == 404.0
    assert ev.gap_abnormal == pytest.approx(0.02 - 0.01)
    assert ev.ret[1] == pytest.approx(107.1 / 102 - 1)  # 5.0%
    assert ev.bench_ret[1] == pytest.approx(408.04 / 404 - 1)  # 1.0%
    assert ev.ar[1] == pytest.approx(0.05 - 0.01)
    assert ev.ar[3] == pytest.approx((110.16 / 102 - 1) - (412.08 / 404 - 1))  # 8% - 2%
    assert ev.ar[5] is None  # window runs past the data: left empty, never filled in


def test_lookahead_trap_future_prices_cannot_change_signal_inputs(cal: TradingCalendar) -> None:
    """Planting absurd prices at the t0 close and later must not move entry or the gap."""
    accepted = datetime(2024, 1, 23, 16, 5, tzinfo=ET)
    clean = compute_event(accepted, bars(STOCK), bars(BENCH), cal)
    trapped_stock = dict(STOCK)
    trapped_stock["2024-01-24"] = (102.0, 1_000_000.0)  # t0 close: after entry
    trapped_stock["2024-01-25"] = (1_000_000.0, 1_000_000.0)
    trapped = compute_event(accepted, bars(trapped_stock), bars(BENCH), cal)
    assert trapped.entry_price == clean.entry_price
    assert trapped.gap_abnormal == clean.gap_abnormal
    assert trapped.ar[1] != clean.ar[1]  # outcomes do change: they are outcomes


def test_pre_market_announcement_enters_same_day(cal: TradingCalendar) -> None:
    ev = compute_event(datetime(2024, 1, 24, 7, 0, tzinfo=ET), bars(STOCK), bars(BENCH), cal)
    assert ev.t0 == date(2024, 1, 24) and ev.entry_price == 102.0


def test_missing_t0_price_leaves_event_empty(cal: TradingCalendar) -> None:
    stock = {k: v for k, v in STOCK.items() if k != "2024-01-24"}
    ev = compute_event(datetime(2024, 1, 23, 16, 5, tzinfo=ET), bars(stock), bars(BENCH), cal)
    assert ev.entry_price is None and ev.ar == {}


# ------------------------------------------------------------------ event study


def test_mean_t_hand_computed() -> None:
    n, mean, sd, t = mean_t(pd.Series([0.01, 0.03, -0.01]))
    assert n == 3 and mean == pytest.approx(0.01) and sd == pytest.approx(0.02)
    assert t == pytest.approx(0.01 / (0.02 / math.sqrt(3)))
    assert mean_t(pd.Series([0.05]))[3] is None  # n < 2: no t-stat
    assert mean_t(pd.Series([None, None], dtype=float))[0] == 0


def test_event_study_groups_and_windows() -> None:
    frame = pd.DataFrame(
        {
            "g": ["raised", "raised", "lowered"],
            "ar_1": [0.02, 0.04, -0.03],
            "ar_3": [0.01, None, -0.05],
            "ar_5": [0.0, 0.0, 0.0],
        }
    )
    stats = {(s.bucket, s.window): s for s in event_study(frame, {"guidance": "g"})}
    assert stats[("raised", 1)].n == 2 and stats[("raised", 1)].mean_ar == pytest.approx(0.03)
    assert stats[("raised", 3)].n == 1  # missing windows are excluded, not zero-filled
    assert stats[("lowered", 1)].mean_ar == pytest.approx(-0.03)


# ------------------------------------------------------------------ metrics


def test_metrics_hand_computed() -> None:
    r = pd.Series([0.01, -0.02, 0.03])
    final = 1.01 * 0.98 * 1.03
    assert annualised_return(r) == pytest.approx(final ** (252 / 3) - 1)
    assert max_drawdown(r) == pytest.approx(0.98 - 1)  # 1.01 -> 0.9898 is -2%
    mean, sd = (
        0.02 / 3,
        math.sqrt(((0.01 - 0.02 / 3) ** 2 + (-0.02 - 0.02 / 3) ** 2 + (0.03 - 0.02 / 3) ** 2) / 2),
    )
    assert sharpe_ratio(r) == pytest.approx(mean / sd * math.sqrt(252))
    assert sharpe_ratio(pd.Series([0.0, 0.0])) is None


def test_drawdown_counts_losses_from_starting_capital() -> None:
    assert max_drawdown(pd.Series([-0.1, 0.05])) == pytest.approx(-0.1)


# ------------------------------------------------------------------ strategies


def test_composite_score_and_thresholds() -> None:
    frame = pd.DataFrame(
        {
            "guidance_direction": ["raised", "lowered", "not_mentioned", None],
            "management_tone": [0.75, 0.25, 0.5, None],
            "revenue_vs_expectation": ["beat", "unknown", "miss", None],
            "eps_vs_expectation": ["unknown", "unknown", "unknown", None],
        }
    )
    w = Weights(guidance=1.0, tone=2.0, revenue=0.5, eps=0.5)
    score = composite_score(frame, w, tone_center=0.5)
    assert score.iloc[0] == pytest.approx(1 + 2 * 0.25 + 0.5)
    assert score.iloc[1] == pytest.approx(-1 + 2 * -0.25)
    assert score.iloc[2] == pytest.approx(-0.5)
    assert pd.isna(score.iloc[3])  # no signal -> no score
    assert threshold_sides(score, 0.5, -0.5).tolist() == [1, -1, 0, 0]


def test_baseline_sides() -> None:
    frame = pd.DataFrame(
        {
            "revenue_vs_expectation": ["beat", "beat", "unknown", "inline"],
            "eps_vs_expectation": ["unknown", "miss", "unknown", "inline"],
            "gap_abnormal": [0.02, -0.02, 0.005, None],
        }
    )
    assert beat_miss_sides(frame).tolist() == [1, -1, 0, 0]  # any miss dominates
    assert gap_sides(frame, 0.01).tolist() == [1, -1, 0, 0]


# ------------------------------------------------------------------ portfolio


PORT = PortfolioConfig(
    hold_days=1, max_positions=2, hedge_with_benchmark=True, cost_bps_per_side=10
)
P_STOCK = {"2024-01-24": (100.0, 102.0), "2024-01-25": (102.0, 103.02)}  # +2%, +1%
P_BENCH = {"2024-01-24": (400.0, 404.0), "2024-01-25": (404.0, 404.0)}  # +1%, 0%


def test_portfolio_pnl_and_costs_hand_computed(cal: TradingCalendar) -> None:
    sim = simulate(
        [Trade(1, "AAA", date(2024, 1, 24), +1)],
        {"AAA": bars(P_STOCK)},
        bars(P_BENCH),
        cal,
        PORT,
        date(2024, 1, 22),
        date(2024, 1, 26),
    )
    # weight 1/2; hedged daily returns 1% and 1%; cost 10bps x 2 legs = 0.2% per side.
    daily = sim.daily_returns
    assert daily[pd.Timestamp("2024-01-24")] == pytest.approx(0.5 * 0.01 - 0.5 * 0.002)
    assert daily[pd.Timestamp("2024-01-25")] == pytest.approx(0.5 * 0.01 - 0.5 * 0.002)
    assert daily[pd.Timestamp("2024-01-22")] == 0.0 and len(daily) == 5
    (t,) = sim.trades
    assert t.gross_return == pytest.approx((1.02 * 1.01 - 1) - 0.01)
    assert t.net_return == pytest.approx(t.gross_return - 2 * 0.002)
    assert t.exit == date(2024, 1, 25)


def test_short_side_flips_pnl(cal: TradingCalendar) -> None:
    sim = simulate(
        [Trade(1, "AAA", date(2024, 1, 24), -1)],
        {"AAA": bars(P_STOCK)},
        bars(P_BENCH),
        cal,
        PORT.model_copy(update={"cost_bps_per_side": 0}),
        date(2024, 1, 22),
        date(2024, 1, 26),
    )
    assert sim.daily_returns[pd.Timestamp("2024-01-24")] == pytest.approx(-0.5 * 0.01)


def test_capacity_keeps_strongest_signal_and_counts_skips(cal: TradingCalendar) -> None:
    trades = [
        Trade(1, "AAA", date(2024, 1, 24), +1, strength=0.5),
        Trade(2, "BBB", date(2024, 1, 24), +1, strength=2.0),
    ]
    prices = {"AAA": bars(P_STOCK), "BBB": bars(P_STOCK)}
    sim = simulate(
        trades,
        prices,
        bars(P_BENCH),
        cal,
        PORT.model_copy(update={"max_positions": 1}),
        date(2024, 1, 22),
        date(2024, 1, 26),
    )
    assert [t.event_id for t in sim.trades] == [2] and sim.skipped_capacity == 1


def test_trades_that_would_exit_after_the_period_are_excluded(cal: TradingCalendar) -> None:
    sim = simulate(
        [Trade(1, "AAA", date(2024, 1, 24), +1)],
        {"AAA": bars(P_STOCK)},
        bars(P_BENCH),
        cal,
        PORT,
        date(2024, 1, 22),
        date(2024, 1, 24),
    )
    assert sim.trades == []


def test_missing_prices_are_counted_not_filled(cal: TradingCalendar) -> None:
    sim = simulate(
        [Trade(1, "AAA", date(2024, 1, 24), +1)],
        {"AAA": bars({"2024-01-24": (100.0, 102.0)})},
        bars(P_BENCH),
        cal,
        PORT,
        date(2024, 1, 22),
        date(2024, 1, 26),
    )
    assert sim.trades == [] and sim.skipped_no_prices == 1
