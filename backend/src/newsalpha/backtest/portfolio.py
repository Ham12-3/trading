"""Daily long/short portfolio simulation over event trades (PRD 10.2).

Conventions (all reported with results):

* A trade enters at the adjusted open of t0 and exits at the adjusted close of t0 + hold_days,
  matching the event-study windows.
* Each position has a fixed weight of 1/max_positions of starting capital; when the book is
  full, new signals that day are skipped (strongest signals first) and counted.
* Daily P&L is ``weight * side * (stock return - benchmark return if hedged)``. Weights are held
  at their entry value (no drift), a standard simplification for short holds.
* Costs: ``cost_bps_per_side`` on entry and on exit, for each leg (stock, and SPY if hedged).
* Uninvested capital earns nothing.
"""

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from newsalpha.backtest.config import PortfolioConfig
from newsalpha.backtest.events import bar_value
from newsalpha.core.calendar import TradingCalendar


@dataclass(frozen=True)
class Trade:
    event_id: int
    symbol: str
    t0: date
    side: int  # +1 long, -1 short
    strength: float = 0.0  # used to prioritise signals when the book is full


@dataclass
class TradeResult:
    event_id: int
    symbol: str
    side: int
    entry: date
    exit: date
    gross_return: float  # side * (stock - bench if hedged), compounded over the hold
    net_return: float  # after entry and exit costs on every leg


@dataclass
class SimulationResult:
    daily_returns: pd.Series
    trades: list[TradeResult] = field(default_factory=list)
    skipped_capacity: int = 0
    skipped_no_prices: int = 0
    avg_positions: float = 0.0
    weight: float = 0.0
    legs: int = 1


def _daily_path(bars: pd.DataFrame, days: list[date]) -> list[float] | None:
    """Per-day returns for a hold: open->close on the first day, close->close after."""
    idx = [pd.Timestamp(d) for d in days]
    if any(ts not in bars.index for ts in idx):
        return None
    closes = [bar_value(bars, ts, "adj_close") for ts in idx]
    first = closes[0] / bar_value(bars, idx[0], "adj_open") - 1.0
    return [first] + [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]


def simulate(
    trades: list[Trade],
    prices: dict[str, pd.DataFrame],
    bench: pd.DataFrame,
    calendar: TradingCalendar,
    config: PortfolioConfig,
    start: date,
    end: date,
) -> SimulationResult:
    """Simulate trades whose whole hold lies inside [start, end]."""
    days = calendar.trading_days(start, end)
    pnl: dict[date, float] = dict.fromkeys(days, 0.0)
    active: dict[date, int] = dict.fromkeys(days, 0)
    weight = 1.0 / config.max_positions
    legs = 2 if config.hedge_with_benchmark else 1
    cost = config.cost_bps_per_side / 10_000 * legs
    result = SimulationResult(daily_returns=pd.Series(dtype=float), weight=weight, legs=legs)

    ordered = sorted(trades, key=lambda t: (t.t0, -abs(t.strength), t.event_id))
    for trade in ordered:
        if trade.side == 0 or not start <= trade.t0 <= end:
            continue
        exit_day = calendar.add_trading_days(trade.t0, config.hold_days)
        if exit_day > end:
            continue
        hold = calendar.trading_days(trade.t0, exit_day)
        bars = prices.get(trade.symbol)
        stock_path = _daily_path(bars, hold) if bars is not None else None
        bench_path = _daily_path(bench, hold)
        if stock_path is None or bench_path is None:
            result.skipped_no_prices += 1
            continue
        if any(active[d] >= config.max_positions for d in hold):
            result.skipped_capacity += 1
            continue

        hedge = bench_path if config.hedge_with_benchmark else [0.0] * len(hold)
        daily = [trade.side * (s - b) for s, b in zip(stock_path, hedge, strict=True)]
        for d, r in zip(hold, daily, strict=True):
            pnl[d] += weight * r
            active[d] += 1
        pnl[hold[0]] -= weight * cost
        pnl[hold[-1]] -= weight * cost

        stock_total = _compound(stock_path)
        hedge_total = _compound(hedge)
        gross = trade.side * (stock_total - hedge_total)
        result.trades.append(
            TradeResult(
                trade.event_id,
                trade.symbol,
                trade.side,
                trade.t0,
                exit_day,
                gross,
                gross - 2 * cost,
            )
        )
    index = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    result.daily_returns = pd.Series(list(pnl.values()), index=index, dtype=float)
    result.avg_positions = sum(active.values()) / len(active) if active else 0.0
    return result


def _compound(path: list[float]) -> float:
    total = 1.0
    for r in path:
        total *= 1.0 + r
    return total - 1.0
