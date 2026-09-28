"""ORM models. Every schema change ships as an Alembic migration."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Double,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
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
