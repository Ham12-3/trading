"""eval_runs: scores of (model, prompt_version) against the gold set.

Revision ID: 0004_eval_runs
Revises: 0003_signals
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_eval_runs"
down_revision: str | None = "0003_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("n_gold", sa.Integer(), nullable=False),
        sa.Column("gold_sha256", sa.String(length=64), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_runs")),
    )
    op.create_index(op.f("ix_eval_runs_model"), "eval_runs", ["model"])


def downgrade() -> None:
    op.drop_index(op.f("ix_eval_runs_model"), table_name="eval_runs")
    op.drop_table("eval_runs")
