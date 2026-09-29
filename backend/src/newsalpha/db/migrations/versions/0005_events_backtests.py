"""events and backtest_runs.

Revision ID: 0005_events_backtests
Revises: 0004_eval_runs
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_events_backtests"
down_revision: str | None = "0004_eval_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RETURN_COLUMNS = [f"{prefix}_{k}" for prefix in ("ret", "bench_ret", "ar") for k in (1, 3, 5)]


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("announcement_id", sa.Integer(), nullable=False),
        sa.Column("t0_date", sa.Date(), nullable=False),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Double(), nullable=True),
        sa.Column("bench_entry_price", sa.Double(), nullable=True),
        sa.Column("gap_abnormal", sa.Double(), nullable=True),
        *[sa.Column(name, sa.Double(), nullable=True) for name in _RETURN_COLUMNS],
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["announcement_id"],
            ["announcements.id"],
            name=op.f("fk_events_announcement_id_announcements"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
        sa.UniqueConstraint("announcement_id", name=op.f("uq_events_announcement_id")),
    )
    op.create_index(op.f("ix_events_t0_date"), "events", ["t0_date"])
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_group", sa.String(length=36), nullable=False),
        sa.Column("strategy", sa.String(length=32), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("equity_curve", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backtest_runs")),
    )
    op.create_index(op.f("ix_backtest_runs_run_group"), "backtest_runs", ["run_group"])


def downgrade() -> None:
    op.drop_index(op.f("ix_backtest_runs_run_group"), table_name="backtest_runs")
    op.drop_table("backtest_runs")
    op.drop_index(op.f("ix_events_t0_date"), table_name="events")
    op.drop_table("events")
