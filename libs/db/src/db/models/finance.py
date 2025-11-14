from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import expression as sa_expr
from sqlalchemy.sql.schema import Computed


class Base(DeclarativeBase):
    pass


# ---------------------------
# Reference: fa_categories
# ---------------------------


class FaCategory(Base):
    __tablename__ = "fa_categories"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    # Note: display_name uniqueness is enforced per-parent via a DB unique index
    # created by Alembic (coalesce(parent_code,'__root__'), lower(display_name)).
    # Do not declare a global unique constraint here.
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    # Optional parent reference; when set, must point to a top-level category
    # (parent has parent_code IS NULL). Two-level depth is enforced in the
    # service layer rather than with recursive DB constraints.
    parent_code: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("fa_categories.code", deferrable=True, initially="DEFERRED"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sort_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


# ---------------------------
# Core: fa_transactions
# ---------------------------


class FaTransaction(Base):
    __tablename__ = "fa_transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_provider: Mapped[str] = mapped_column(String, nullable=False)
    source_account: Mapped[str | None] = mapped_column(String, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    fingerprint_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    raw_record: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    currency_code: Mapped[str] = mapped_column(
        CHAR(3), nullable=False, server_default=text("'USD'")
    )
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    merchant: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Normalized merchant/description key used for duplicate matching.
    #
    # Semantics align with the in-process grouping key in
    # `packages/financial_analysis/review.py::_norm_merchant_key`:
    # - prefer `merchant`; when empty/NULL, fall back to `description`;
    # - collapse internal whitespace (tabs/newlines) to a single space;
    # - trim leading/trailing spaces; lower-case the result.
    #
    # Postgres does not provide Python's full `casefold()`/NFKC behavior, so we
    # approximate via LOWER() on a whitespace-collapsed string. This matches the
    # vast majority of ASCII merchant strings seen in practice and keeps the
    # computation immutable for a generated column + btree index.
    merchant_norm: Mapped[str | None] = mapped_column(
        Text,
        Computed(
            sa_expr.text(
                "NULLIF(BTRIM(LOWER(REGEXP_REPLACE(COALESCE("
                "NULLIF(BTRIM(merchant), ''), NULLIF(BTRIM(description), '')), "
                "'[[:space:]]+', ' ', 'g'))), '')"
            ),
            persisted=True,
        ),
        nullable=True,
    )
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional human-friendly label shown in UIs/reports. Raw provider fields
    # (description/merchant/raw_record) remain the source of truth for
    # matching/deduplication and are never mutated by rename operations.
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name_source: Mapped[str] = mapped_column(
        String,
        nullable=False,
        server_default=text("'unknown'"),
    )
    renamed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    category: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("fa_categories.code", deferrable=True, initially="DEFERRED"),
        nullable=True,
    )
    category_source: Mapped[str] = mapped_column(
        String,
        nullable=False,
        server_default=text("'unknown'"),
    )
    category_confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    categorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint(
            "category_source in ('llm','manual','rule','import','unknown')",
            name="ck_fa_tx_category_source",
        ),
        CheckConstraint(
            "display_name_source in ('manual','rule','import','unknown')",
            name="ck_fa_tx_display_name_source",
        ),
        CheckConstraint(
            (
                "category_confidence IS NULL OR "
                "(category_confidence >= 0 AND category_confidence <= 1)"
            ),
            name="ck_fa_tx_category_confidence",
        ),
    )


__all__ = [
    "Base",
    "FaCategory",
    "FaTransaction",
]
