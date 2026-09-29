"""Ingestion tables: companies, announcements, prices_daily.

Revision ID: 0002_ingestion_tables
Revises: 0001_baseline
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_ingestion_tables"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("cik", sa.BigInteger(), nullable=False),
        sa.Column("sector", sa.String(length=64), nullable=True),
        sa.Column("exchange", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_companies")),
        sa.UniqueConstraint("cik", name=op.f("uq_companies_cik")),
        sa.UniqueConstraint("ticker", name=op.f("uq_companies_ticker")),
    )
    op.create_table(
        "announcements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("form_type", sa.String(length=16), nullable=False),
        sa.Column("item_codes", postgresql.ARRAY(sa.String(length=8)), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("raw_text_uri", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_announcements_company_id_companies"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_announcements")),
        sa.UniqueConstraint("source", "source_id", name=op.f("uq_announcements_source")),
    )
    op.create_index(
        op.f("ix_announcements_accepted_at"), "announcements", ["accepted_at"], unique=False
    )
    op.create_index(
        op.f("ix_announcements_company_id"), "announcements", ["company_id"], unique=False
    )
    op.create_index(
        op.f("ix_announcements_text_hash"), "announcements", ["text_hash"], unique=False
    )
    op.create_table(
        "prices_daily",
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Double(), nullable=False),
        sa.Column("high", sa.Double(), nullable=False),
        sa.Column("low", sa.Double(), nullable=False),
        sa.Column("close", sa.Double(), nullable=False),
        sa.Column("adj_close", sa.Double(), nullable=False),
        sa.Column("adj_open", sa.Double(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "date", name=op.f("pk_prices_daily")),
    )


def downgrade() -> None:
    op.drop_table("prices_daily")
    op.drop_index(op.f("ix_announcements_text_hash"), table_name="announcements")
    op.drop_index(op.f("ix_announcements_company_id"), table_name="announcements")
    op.drop_index(op.f("ix_announcements_accepted_at"), table_name="announcements")
    op.drop_table("announcements")
    op.drop_table("companies")
