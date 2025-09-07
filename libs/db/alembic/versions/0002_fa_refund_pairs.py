# ruff: noqa: I001
"""Refund link pairs table.

Revision ID: 0002_fa_refund_pairs
Revises: 0001_fa_core
Create Date: 2025-09-07
"""

from __future__ import annotations  # ruff: noqa: I001

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0002_fa_refund_pairs"
down_revision: str | None = "0001_fa_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fa_refund_pairs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("expense_id", sa.BigInteger(), nullable=False),
        sa.Column("refund_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["expense_id"], ["fa_transactions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["refund_id"], ["fa_transactions.id"], ondelete="CASCADE"),
        sa.CheckConstraint("expense_id <> refund_id", name="ck_fa_refund_pairs_distinct"),
    )

    op.create_unique_constraint(
        "uq_fa_refund_pairs_expense_refund", "fa_refund_pairs", ["expense_id", "refund_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_fa_refund_pairs_expense_refund", "fa_refund_pairs", type_="unique")
    op.drop_table("fa_refund_pairs")
