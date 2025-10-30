# ruff: noqa: I001
"""Add normalized-merchant generated column and composite index.

Revision ID: 0004_tx_merchant_norm
Revises: 0003_tx_display_name
Create Date: 2025-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0004_tx_merchant_norm"
down_revision: str | None = "0003_tx_display_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Generated, normalized merchant/description key used for duplicate matching.
    #
    # Expression details:
    # - prefer merchant when present/non-empty, else fall back to description
    # - collapse internal whitespace to a single space
    # - trim and lower-case; empty string -> NULL
    expr = sa.text(
        "NULLIF(BTRIM(LOWER(REGEXP_REPLACE(COALESCE("  # noqa: E501
        "NULLIF(BTRIM(merchant), ''), NULLIF(BTRIM(description), '')), "
        "'[[:space:]]+', ' ', 'g'))), '')"
    )

    op.add_column(
        "fa_transactions",
        sa.Column("merchant_norm", sa.Text(), sa.Computed(expr, persisted=True), nullable=True),
    )

    # Composite index to support provider/account-scoped lookups by normalized merchant
    op.create_index(
        "ix_fa_tx_provider_account_merchant_norm",
        "fa_transactions",
        ["source_provider", "source_account", "merchant_norm"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_fa_tx_provider_account_merchant_norm", table_name="fa_transactions")
    op.drop_column("fa_transactions", "merchant_norm")
