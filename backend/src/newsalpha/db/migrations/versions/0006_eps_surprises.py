"""eps_surprises: analyst EPS consensus vs reported EPS per company-quarter.

Revision ID: 0006_eps_surprises
Revises: 0005_events_backtests
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_eps_surprises"
down_revision: str | None = "0005_events_backtests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eps_surprises",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("earnings_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("eps_estimate", sa.Double(), nullable=True),
        sa.Column("eps_reported", sa.Double(), nullable=True),
        sa.Column("surprise_pct", sa.Double(), nullable=True),
        sa.Column("announcement_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["announcement_id"],
            ["announcements.id"],
            name=op.f("fk_eps_surprises_announcement_id_announcements"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_eps_surprises_company_id_companies")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eps_surprises")),
        sa.UniqueConstraint("announcement_id", name=op.f("uq_eps_surprises_announcement_id")),
        sa.UniqueConstraint("company_id", "earnings_at", name=op.f("uq_eps_surprises_company_id")),
    )
    op.create_index(op.f("ix_eps_surprises_company_id"), "eps_surprises", ["company_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_eps_surprises_company_id"), table_name="eps_surprises")
    op.drop_table("eps_surprises")
