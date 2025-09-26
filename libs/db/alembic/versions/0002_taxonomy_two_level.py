# ruff: noqa: I001
"""Two-level taxonomy: add parent_code and per-parent name uniqueness.

Revision ID: 0002_taxonomy_two_level
Revises: 0001_fa_core
Create Date: 2025-09-25
"""

from __future__ import annotations  # ruff: noqa: I001

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0002_taxonomy_two_level"
down_revision: str | None = "0001_fa_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) Schema changes: add parent_code, drop global unique on display_name
    op.add_column("fa_categories", sa.Column("parent_code", sa.Text(), nullable=True))

    # Drop the global unique constraint created in 0001. The default name in
    # Postgres for a column-level unique is "{table}_{column}_key".
    op.drop_constraint("fa_categories_display_name_key", "fa_categories", type_="unique")

    # Add explicit self-referential FK on parent_code (deferrable, initially deferred)
    op.create_foreign_key(
        "fk_fa_cat_parent",
        source_table="fa_categories",
        referent_table="fa_categories",
        local_cols=["parent_code"],
        remote_cols=["code"],
        deferrable=True,
        initially="DEFERRED",
    )

    # Prevent self-loop (parent_code == code)
    op.create_check_constraint(
        "ck_fa_cat_no_self_parent",
        "fa_categories",
        condition=sa.text("(parent_code IS NULL OR parent_code <> code)"),
    )

    # Per-parent, case-insensitive uniqueness for display_name
    op.create_index(
        "uniq_fa_cat_parent_display_name_ci",
        "fa_categories",
        [sa.text("COALESCE(parent_code, '__root__')"), sa.text("lower(display_name)")],
        unique=True,
    )

    # Helpful lookup index for building pickers
    op.create_index("ix_fa_categories_parent_code", "fa_categories", ["parent_code"], unique=False)

    # 2) Destructive data step (pre-launch): clear existing transaction category assignments
    op.execute("UPDATE fa_transactions SET category = NULL")


def downgrade() -> None:
    op.drop_index("ix_fa_categories_parent_code", table_name="fa_categories")
    op.drop_index("uniq_fa_cat_parent_display_name_ci", table_name="fa_categories")
    op.drop_constraint("ck_fa_cat_no_self_parent", table_name="fa_categories")
    op.drop_constraint("fk_fa_cat_parent", table_name="fa_categories")
    op.drop_column("fa_categories", "parent_code")
    # Recreate the original global uniqueness on display_name
    op.create_unique_constraint("fa_categories_display_name_key", "fa_categories", ["display_name"])
