"""ORM models. Every schema change ships as an Alembic migration."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newsalpha.db.base import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    cik: Mapped[int] = mapped_column(BigInteger, unique=True)
    sector: Mapped[str | None] = mapped_column(String(64))
    exchange: Mapped[str | None] = mapped_column(String(32))

    announcements: Mapped[list["Announcement"]] = relationship(back_populates="company")


class Announcement(Base):
    __tablename__ = "announcements"
    __table_args__ = (UniqueConstraint("source", "source_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    source: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(64))
    # Point-in-time anchor: when the source accepted/published it (stored in UTC).
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    form_type: Mapped[str] = mapped_column(String(16))
    item_codes: Mapped[list[str]] = mapped_column(ARRAY(String(8)))
    url: Mapped[str] = mapped_column(Text)
    raw_text_uri: Mapped[str] = mapped_column(Text)  # local path now, s3:// later
    text_hash: Mapped[str] = mapped_column(String(64), index=True)  # sha256 of stored text
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    company: Mapped[Company] = relationship(back_populates="announcements")


class Signal(Base):
    """One LLM extraction of one announcement by one (model, prompt_version)."""

    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("announcement_id", "model", "prompt_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    announcement_id: Mapped[int] = mapped_column(ForeignKey("announcements.id"), index=True)
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    document_hash: Mapped[str] = mapped_column(String(64), index=True)  # cache key part
    status: Mapped[str] = mapped_column(String(16), index=True)  # "ok" | "failed"
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer)
    truncated: Mapped[bool] = mapped_column(Boolean)
    cache_hit: Mapped[bool] = mapped_column(Boolean)
    input_tokens: Mapped[int] = mapped_column(Integer)
    cached_input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[float] = mapped_column(Double)
    latency_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalRun(Base):
    """One scoring of (model, prompt_version) against the gold set."""

    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    model: Mapped[str] = mapped_column(String(64), index=True)
    prompt_version: Mapped[str] = mapped_column(String(32))
    n_gold: Mapped[int] = mapped_column(Integer)
    gold_sha256: Mapped[str] = mapped_column(String(64))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Event(Base):
    """Per-announcement event: t0, entry prices, opening gap and abnormal returns (PRD 10.1).

    ``ret_k``/``bench_ret_k``/``ar_k`` run from the t0 adjusted open to the adjusted close of
    trading day t0+k. They are outcomes and must never be used as signal inputs.
    """

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    announcement_id: Mapped[int] = mapped_column(ForeignKey("announcements.id"), unique=True)
    t0_date: Mapped[date] = mapped_column(Date, index=True)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entry_price: Mapped[float | None] = mapped_column(Double)
    bench_entry_price: Mapped[float | None] = mapped_column(Double)
    gap_abnormal: Mapped[float | None] = mapped_column(Double)
    ret_1: Mapped[float | None] = mapped_column(Double)
    ret_3: Mapped[float | None] = mapped_column(Double)
    ret_5: Mapped[float | None] = mapped_column(Double)
    bench_ret_1: Mapped[float | None] = mapped_column(Double)
    bench_ret_3: Mapped[float | None] = mapped_column(Double)
    bench_ret_5: Mapped[float | None] = mapped_column(Double)
    ar_1: Mapped[float | None] = mapped_column(Double)
    ar_3: Mapped[float | None] = mapped_column(Double)
    ar_5: Mapped[float | None] = mapped_column(Double)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BacktestRun(Base):
    """One strategy on one period. Runs made together share ``run_group``."""

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_group: Mapped[str] = mapped_column(String(36), index=True)
    strategy: Mapped[str] = mapped_column(String(32))
    period: Mapped[str] = mapped_column(String(16))  # "in_sample" | "out_of_sample"
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    equity_curve: Mapped[list[Any]] = mapped_column(JSONB)  # [[date, equity, drawdown], ...]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EpsSurprise(Base):
    """Analyst EPS consensus vs reported EPS for one company-quarter (non-LLM input).

    ``announcement_id`` links the quarter to its earnings release when the report dates match
    (within a day); it stays NULL for quarters outside the study or releases that are not
    earnings reports.
    """

    __tablename__ = "eps_surprises"
    __table_args__ = (UniqueConstraint("company_id", "earnings_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    earnings_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    eps_estimate: Mapped[float | None] = mapped_column(Double)
    eps_reported: Mapped[float | None] = mapped_column(Double)
    surprise_pct: Mapped[float | None] = mapped_column(Double)  # (reported-estimate)/|estimate|
    announcement_id: Mapped[int | None] = mapped_column(ForeignKey("announcements.id"), unique=True)
    source: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PriceDaily(Base):
    """Daily bar keyed by symbol so stocks and benchmarks (SPY) share one table."""

    __tablename__ = "prices_daily"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float] = mapped_column(Double)
    high: Mapped[float] = mapped_column(Double)
    low: Mapped[float] = mapped_column(Double)
    close: Mapped[float] = mapped_column(Double)
    adj_close: Mapped[float] = mapped_column(Double)
    adj_open: Mapped[float] = mapped_column(Double)
    volume: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(32))
