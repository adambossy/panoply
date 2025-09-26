# ruff: noqa: I001
"""Add optional display-name fields to transactions for human-friendly labels.

Revision ID: 0003_tx_display_name
Revises: 0002_taxonomy_two_level
Create Date: 2025-09-26
"""

from __future__ import annotations  # ruff: noqa: I001

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0003_tx_display_name"
down_revision: str | None = "0002_taxonomy_two_level"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add columns to fa_transactions to support human-friendly display labels
    op.add_column("fa_transactions", sa.Column("display_name", sa.Text(), nullable=True))
    op.add_column(
        "fa_transactions",
        sa.Column(
            "display_name_source", sa.String(), nullable=False, server_default=sa.text("'unknown'")
        ),
    )
    op.add_column(
        "fa_transactions",
        sa.Column("renamed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Lightweight lookup index for ad-hoc queries
    op.create_index(
        "ix_fa_transactions_display_name",
        "fa_transactions",
        ["display_name"],
        unique=False,
    )

    # Enforce allowed sources for display_name_source
    op.create_check_constraint(
        "ck_fa_tx_display_name_source",
        "fa_transactions",
        condition=sa.text("display_name_source in ('manual','rule','import','unknown')"),
    )


def downgrade() -> None:
    op.drop_constraint("ck_fa_tx_display_name_source", table_name="fa_transactions")
    op.drop_index("ix_fa_transactions_display_name", table_name="fa_transactions")
    op.drop_column("fa_transactions", "renamed_at")
    op.drop_column("fa_transactions", "display_name_source")
    op.drop_column("fa_transactions", "display_name")
