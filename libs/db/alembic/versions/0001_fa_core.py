# ruff: noqa: I001
"""Finance core tables and seed categories.

Revision ID: 0001_fa_core
Revises: None
Create Date: 2025-09-07
"""

from __future__ import annotations  # ruff: noqa: I001

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0001_fa_core"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # fa_categories
    op.create_table(
        "fa_categories",
        sa.Column("code", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("sort_order", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Seed categories from financial_analysis.categorization.ALLOWED_CATEGORIES (mirrored here)
    allowed_categories = (
        "Groceries",
        "Restaurants",
        "Coffee Shops",
        "Flights",
        "Hotels",
        "Clothing",
        "Shopping",
        "Baby",
        "House",
        "Pet",
        "Emergency",
        "Medical",
        "Other",
    )
    op.bulk_insert(
        sa.table(
            "fa_categories",
            sa.column("code", sa.Text()),
            sa.column("display_name", sa.Text()),
            sa.column("is_active", sa.Boolean()),
            sa.column("sort_order", sa.Integer()),
        ),
        [
            {"code": c, "display_name": c, "is_active": True, "sort_order": i}
            for i, c in enumerate(allowed_categories)
        ],
    )

    # fa_transactions
    op.create_table(
        "fa_transactions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_provider", sa.Text(), nullable=False),
        sa.Column("source_account", sa.Text(), nullable=True),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("fingerprint_sha256", sa.CHAR(64), nullable=False, unique=True),
        sa.Column("raw_record", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "currency_code",
            sa.CHAR(3),
            nullable=False,
            server_default=sa.text("'USD'"),
        ),
        sa.Column("amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("merchant", sa.Text(), nullable=True),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column(
            "category_source",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
        sa.Column("category_confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("categorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["category"],
            ["fa_categories.code"],
            name="fk_fa_tx_category",
            deferrable=True,
            initially="DEFERRED",
            use_alter=False,
        ),
        sa.CheckConstraint(
            "category_source in ('llm','manual','rule','import','unknown')",
            name="ck_fa_tx_category_source",
        ),
        sa.CheckConstraint(
            (
                "category_confidence IS NULL OR "
                "(category_confidence >= 0 AND category_confidence <= 1)"
            ),
            name="ck_fa_tx_category_confidence",
        ),
    )

    # Indexes and uniques
    op.create_index(
        "uq_fa_tx_fingerprint",
        "fa_transactions",
        ["fingerprint_sha256"],
        unique=True,
    )
    op.create_index(
        "uniq_fa_tx_provider_external_id",
        "fa_transactions",
        ["source_provider", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.create_index("ix_fa_transactions_date", "fa_transactions", ["date"], unique=False)
    op.create_index("ix_fa_transactions_category", "fa_transactions", ["category"], unique=False)
    op.create_index("ix_fa_transactions_merchant", "fa_transactions", ["merchant"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_fa_transactions_merchant", table_name="fa_transactions")
    op.drop_index("ix_fa_transactions_category", table_name="fa_transactions")
    op.drop_index("ix_fa_transactions_date", table_name="fa_transactions")
    op.drop_index("uniq_fa_tx_provider_external_id", table_name="fa_transactions")
    op.drop_index("uq_fa_tx_fingerprint", table_name="fa_transactions")
    op.drop_table("fa_transactions")
    op.drop_table("fa_categories")
