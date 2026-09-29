"""Event study tables and portfolio backtests."""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from newsalpha.backtest.config import BacktestConfig, load_backtest_config
from newsalpha.backtest.event_study import BucketStat, event_study
from newsalpha.backtest.runner import (
    GROUPINGS,
    add_buckets,
    in_period,
    load_event_frame,
    run_backtest,
)
from newsalpha.core.calendar import get_calendar
from newsalpha.db.models import BacktestRun
from newsalpha.db.session import get_session

router = APIRouter(tags=["backtests"])
SessionDep = Annotated[Session, Depends(get_session)]
PeriodName = Literal["all", "in_sample", "out_of_sample"]


class PeriodOut(BaseModel):
    start: date
    end: date


class EventSummaryOut(BaseModel):
    model: str
    prompt_version: str
    period: PeriodName
    periods: dict[str, PeriodOut]
    n_events: int
    stats: list[BucketStat]


@router.get("/events/summary", response_model=EventSummaryOut)
def events_summary(session: SessionDep, period: PeriodName = "all") -> EventSummaryOut:
    """Mean abnormal return (vs SPY, from the t0 open), t-stat and n per bucket and window.

    Tone-tercile cut points are fitted on in-sample events only. t-stats assume independent
    events, which overstates significance when announcements cluster in time.
    """
    config = load_backtest_config()
    frame = load_event_frame(session, config.signals.model, config.signals.prompt_version)
    if frame.empty:
        raise HTTPException(status_code=404, detail="no events; run `newsalpha events build`")
    frame = add_buckets(frame, config)
    if period != "all":
        frame = in_period(frame, getattr(config.periods, period))
    return EventSummaryOut(
        model=config.signals.model,
        prompt_version=config.signals.prompt_version,
        period=period,
        periods={
            "in_sample": PeriodOut(**config.periods.in_sample.model_dump()),
            "out_of_sample": PeriodOut(**config.periods.out_of_sample.model_dump()),
        },
        n_events=len(frame),
        stats=event_study(frame, GROUPINGS),
    )


class BacktestRunOut(BaseModel):
    id: int
    run_group: str
    strategy: str
    period: str
    metrics: dict[str, Any]
    created_at: datetime
    equity_curve: list[list[Any]] | None = None  # [[date, equity, drawdown], ...]


class BacktestGroupOut(BaseModel):
    run_group: str
    created_at: datetime
    config: dict[str, Any]  # configuration, fitted parameters and the tuning grid
    runs: list[BacktestRunOut]


def _run_out(run: BacktestRun, with_curve: bool) -> BacktestRunOut:
    return BacktestRunOut(
        id=run.id,
        run_group=run.run_group,
        strategy=run.strategy,
        period=run.period,
        metrics=run.metrics,
        created_at=run.created_at,
        equity_curve=run.equity_curve if with_curve else None,
    )


def _group_out(runs: list[BacktestRun], with_curves: bool) -> BacktestGroupOut:
    return BacktestGroupOut(
        run_group=runs[0].run_group,
        created_at=runs[0].created_at,
        config=runs[0].config,
        runs=[_run_out(r, with_curves) for r in runs],
    )


@router.get("/backtests", response_model=BacktestGroupOut)
def get_backtest_group(
    session: SessionDep,
    run_group: str | None = None,
    curves: Annotated[bool, Query(description="Include equity curves")] = True,
) -> BacktestGroupOut:
    """All runs of one group (default: the latest group)."""
    group = run_group or session.scalar(
        select(BacktestRun.run_group).order_by(BacktestRun.created_at.desc()).limit(1)
    )
    runs = list(
        session.scalars(
            select(BacktestRun).where(BacktestRun.run_group == group).order_by(BacktestRun.id)
        )
    )
    if not runs:
        raise HTTPException(
            status_code=404, detail="no backtest runs; run `newsalpha backtest run`"
        )
    return _group_out(runs, curves)


@router.get("/backtests/{run_id}", response_model=BacktestRunOut)
def get_backtest(run_id: int, session: SessionDep) -> BacktestRunOut:
    run = session.get(BacktestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="backtest run not found")
    return _run_out(run, with_curve=True)


@router.post("/backtests", response_model=BacktestGroupOut, status_code=201)
def create_backtest(
    config: BacktestConfig,
    session: SessionDep,
    tune: Annotated[bool, Query(description="Tune on in-sample before running")] = True,
) -> BacktestGroupOut:
    """Run every strategy on both periods with the given config and store the runs."""
    try:
        _, runs = run_backtest(session, config, get_calendar(), do_tune=tune)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _group_out(runs, with_curves=False)
