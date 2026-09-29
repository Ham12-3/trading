"""Backtest orchestration: load events + signals, fit on in-sample, run all strategies on both
periods, and store the results."""

import itertools
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from newsalpha.backtest.config import BacktestConfig, Period, Weights
from newsalpha.backtest.events import load_price_panel
from newsalpha.backtest.metrics import (
    annualised_return,
    annualised_volatility,
    drawdown,
    equity_curve,
    max_drawdown,
    sharpe_ratio,
)
from newsalpha.backtest.portfolio import SimulationResult, Trade, simulate
from newsalpha.backtest.strategy import (
    beat_miss_sides,
    composite_score,
    gap_sides,
    threshold_sides,
)
from newsalpha.core.calendar import TradingCalendar
from newsalpha.db.models import Announcement, BacktestRun, Company, Event, Signal

SIGNAL_FIELDS = (
    "guidance_direction",
    "revenue_vs_expectation",
    "eps_vs_expectation",
    "management_tone",
)
STRATEGIES = ("llm_composite", "baseline_opening_gap", "baseline_beat_miss")


def load_event_frame(session: Session, model: str, prompt_version: str) -> pd.DataFrame:
    """One row per event with its LLM signals (NaN where the extraction is missing/failed)."""
    rows = session.execute(
        select(
            Event.id,
            Event.announcement_id,
            Company.ticker,
            Event.t0_date,
            Event.gap_abnormal,
            Event.ar_1,
            Event.ar_3,
            Event.ar_5,
            Signal.payload,
        )
        .join(Announcement, Announcement.id == Event.announcement_id)
        .join(Company, Company.id == Announcement.company_id)
        .outerjoin(
            Signal,
            (Signal.announcement_id == Event.announcement_id)
            & (Signal.model == model)
            & (Signal.prompt_version == prompt_version)
            & (Signal.status == "ok"),
        )
        .where(Event.entry_price.is_not(None))
    ).all()
    records = []
    for eid, aid, ticker, t0, gap, ar1, ar3, ar5, payload in rows:
        rec: dict[str, Any] = {
            "event_id": eid,
            "announcement_id": aid,
            "symbol": ticker,
            "t0": t0,
            "gap_abnormal": gap,
            "ar_1": ar1,
            "ar_3": ar3,
            "ar_5": ar5,
        }
        for f in SIGNAL_FIELDS:
            rec[f] = payload.get(f) if payload else None
        records.append(rec)
    frame = pd.DataFrame.from_records(records)
    if not frame.empty:
        frame["management_tone"] = pd.to_numeric(frame["management_tone"])
    return frame.sort_values(["t0", "event_id"]).reset_index(drop=True)


def in_period(frame: pd.DataFrame, period: Period) -> pd.DataFrame:
    return frame[(frame["t0"] >= period.start) & (frame["t0"] <= period.end)]


def fit_tone_center(frame: pd.DataFrame, config: BacktestConfig) -> float:
    """Tone center: a fixed number, or the median tone of in-sample events only."""
    center = config.composite.tone_center
    if isinstance(center, float | int):
        return float(center)
    tones = in_period(frame, config.periods.in_sample)["management_tone"].dropna()
    if tones.empty:
        raise ValueError("no in-sample signals to fit the tone center")
    return float(tones.median())


@dataclass(frozen=True)
class LLMParams:
    weights: Weights
    tone_center: float
    long_threshold: float
    short_threshold: float


def strategy_trades(
    frame: pd.DataFrame, strategy: str, config: BacktestConfig, params: LLMParams
) -> list[Trade]:
    if strategy == "llm_composite":
        score = composite_score(frame, params.weights, params.tone_center)
        sides = threshold_sides(score, params.long_threshold, params.short_threshold)
        strength = score.fillna(0.0)
    elif strategy == "baseline_opening_gap":
        sides = gap_sides(frame, config.baselines.opening_gap_threshold)
        strength = frame["gap_abnormal"].abs().fillna(0.0)
    elif strategy == "baseline_beat_miss":
        sides = beat_miss_sides(frame)
        strength = pd.Series(0.0, index=frame.index)
    else:
        raise ValueError(f"unknown strategy {strategy!r}")
    return [
        Trade(int(eid), str(sym), t0, int(s), float(st))
        for eid, sym, t0, s, st in zip(
            frame["event_id"].tolist(),
            frame["symbol"].tolist(),
            frame["t0"].tolist(),
            sides.tolist(),
            strength.tolist(),
            strict=True,
        )
        if s != 0
    ]


def summarise(sim: SimulationResult, start: date, end: date) -> dict[str, Any]:
    r = sim.daily_returns
    years = len(r) / 252 if len(r) else 0.0
    nets = [t.net_return for t in sim.trades]
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "n_days": len(r),
        "total_return": float(np.prod(1.0 + r.to_numpy(dtype=float)) - 1.0),
        "annualised_return": annualised_return(r),
        "annualised_volatility": annualised_volatility(r),
        "sharpe": sharpe_ratio(r),
        "max_drawdown": max_drawdown(r),
        "n_trades": len(sim.trades),
        "n_long": sum(t.side > 0 for t in sim.trades),
        "n_short": sum(t.side < 0 for t in sim.trades),
        "hit_rate": sum(n > 0 for n in nets) / len(nets) if nets else None,
        "mean_trade_net_return": sum(nets) / len(nets) if nets else None,
        "skipped_capacity": sim.skipped_capacity,
        "skipped_no_prices": sim.skipped_no_prices,
        "avg_positions": sim.avg_positions,
        "avg_gross_exposure": sim.avg_positions * sim.weight,  # stock leg, fraction of capital
        # Annual turnover: stock-leg notional traded (entry + exit) per year, x capital.
        "turnover_annual": (len(sim.trades) * 2 * sim.weight / years) if years else 0.0,
    }


def curve_points(sim: SimulationResult) -> list[list[Any]]:
    eq = equity_curve(sim.daily_returns)
    dd = drawdown(eq)
    return [
        [ts.date().isoformat(), round(float(e), 6), round(float(d), 6)]
        for ts, e, d in zip(eq.index, eq, dd, strict=True)
    ]


def tune(
    frame: pd.DataFrame,
    config: BacktestConfig,
    tone_center: float,
    prices: dict[str, pd.DataFrame],
    bench: pd.DataFrame,
    calendar: TradingCalendar,
) -> tuple[LLMParams, list[dict[str, Any]]]:
    """Grid over symmetric thresholds and tone weight; in-sample Sharpe only."""
    period = config.periods.in_sample
    sample = in_period(frame, period)
    grid = []
    best: tuple[float, LLMParams] | None = None
    for thr, tw in itertools.product(config.tuning.thresholds, config.tuning.tone_weights):
        params = LLMParams(
            weights=config.composite.weights.model_copy(update={"tone": tw}),
            tone_center=tone_center,
            long_threshold=thr,
            short_threshold=-thr,
        )
        sim = simulate(
            strategy_trades(sample, "llm_composite", config, params),
            prices,
            bench,
            calendar,
            config.portfolio,
            period.start,
            period.end,
        )
        sharpe = sharpe_ratio(sim.daily_returns)
        grid.append(
            {"threshold": thr, "tone_weight": tw, "sharpe": sharpe, "n_trades": len(sim.trades)}
        )
        if sharpe is not None and (best is None or sharpe > best[0]):
            best = (sharpe, params)
    if best is None:
        raise ValueError("tuning produced no trades in-sample; widen the grid")
    return best[1], grid


def run_backtest(
    session: Session,
    config: BacktestConfig,
    calendar: TradingCalendar,
    benchmark: str = "SPY",
    do_tune: bool = True,
) -> tuple[str, list[BacktestRun]]:
    """Run every strategy on both periods; store and return the runs (sharing a run_group)."""
    frame = load_event_frame(session, config.signals.model, config.signals.prompt_version)
    if frame.empty:
        raise ValueError("no events; run `newsalpha events build` first")
    if frame["guidance_direction"].isna().all():
        raise ValueError(
            f"no ok signals for {config.signals.model}/{config.signals.prompt_version}"
        )
    prices = load_price_panel(session, sorted(set(frame["symbol"]) | {benchmark}))
    bench = prices[benchmark]
    tone_center = fit_tone_center(frame, config)
    grid: list[dict[str, Any]] = []
    if do_tune:
        params, grid = tune(frame, config, tone_center, prices, bench, calendar)
    else:
        params = LLMParams(
            config.composite.weights,
            tone_center,
            config.composite.long_threshold,
            config.composite.short_threshold,
        )

    group = str(uuid.uuid4())
    used = {
        "config": config.model_dump(mode="json"),
        "fitted": {
            "tone_center": tone_center,
            "weights": params.weights.model_dump(),
            "long_threshold": params.long_threshold,
            "short_threshold": params.short_threshold,
            "tuned_on": "in_sample" if do_tune else None,
        },
        "tuning_grid": grid,
        "n_events_with_signals": int(frame["guidance_direction"].notna().sum()),
    }
    runs = []
    periods = {"in_sample": config.periods.in_sample, "out_of_sample": config.periods.out_of_sample}
    for strategy in STRATEGIES:
        for name, period in periods.items():
            trades = strategy_trades(in_period(frame, period), strategy, config, params)
            sim = simulate(
                trades, prices, bench, calendar, config.portfolio, period.start, period.end
            )
            run = BacktestRun(
                run_group=group,
                strategy=strategy,
                period=name,
                config=used,
                metrics=summarise(sim, period.start, period.end),
                equity_curve=curve_points(sim),
            )
            session.add(run)
            runs.append(run)
    session.commit()
    return group, runs


GROUPINGS = {
    "guidance_direction": "guidance_direction",
    "tone_tercile": "tone_tercile",
    "beat_miss": "beat_miss",
    "opening_gap": "gap_bucket",
}


def _tone_bucket(tone: float | None, lo: float, hi: float) -> str | None:
    if tone is None or pd.isna(tone):
        return None
    if tone <= lo:
        return f"low (<= {lo:.2f})"
    return f"mid (<= {hi:.2f})" if tone <= hi else f"high (> {hi:.2f})"


def _gap_bucket(gap: float | None, threshold: float) -> str | None:
    if gap is None or pd.isna(gap):
        return None
    return "gap up" if gap > threshold else "gap down" if gap < -threshold else "flat"


def add_buckets(frame: pd.DataFrame, config: BacktestConfig) -> pd.DataFrame:
    """Bucket columns for the event study. Tone tercile cut points come from in-sample only."""
    out = frame.copy()
    tones = in_period(frame, config.periods.in_sample)["management_tone"].dropna()
    lo = float(tones.quantile(1 / 3)) if len(tones) else 0.0
    hi = float(tones.quantile(2 / 3)) if len(tones) else 0.0
    out["tone_tercile"] = [_tone_bucket(t, lo, hi) for t in out["management_tone"].tolist()]
    sides = beat_miss_sides(out).tolist()
    has_signal = out["revenue_vs_expectation"].notna().tolist()
    out["beat_miss"] = [
        None if not ok else "beat" if s > 0 else "miss" if s < 0 else "neither"
        for ok, s in zip(has_signal, sides, strict=True)
    ]
    thr = config.baselines.opening_gap_threshold
    out["gap_bucket"] = [_gap_bucket(g, thr) for g in out["gap_abnormal"].tolist()]
    return out
