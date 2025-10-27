"""Duplicate lookup and persistence helpers shared by review and categorize.

This module exposes a small, public API that both the interactive review flow
(`review.py`) and the DB‑first prefill path (`categorize.py`) can depend on
without importing private internals from either module.

Public surface:
- ``PreparedItem``: lightweight, immutable view of an input row with
  identifiers used for DB lookups and persistence.
- ``query_group_duplicates``: return a sample of duplicate rows from the DB and
  the unanimous non‑null category when present.
- ``persist_group``: upsert the group's transactions and set the chosen
  category and related metadata in a single batched update (commit at caller).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from db.models.finance import FaTransaction
from sqlalchemy import distinct, func, or_, select, update
from sqlalchemy.orm import Session

from .persistence import upsert_transactions


@dataclass(frozen=True, slots=True)
class PreparedItem:
    """Prepared view of an input row with identifiers for grouping/DB lookups."""

    pos: int
    tx: Mapping[str, Any]
    external_id: str | None
    fingerprint: str
    # Used only by interactive review for display/defaults; ignored in persistence
    suggested: str = ""


def query_group_duplicates(
    session: Session,
    *,
    source_provider: str,
    source_account: str | None,
    group_eids: list[str],
    group_fps: list[str],
    exemplars: int = 1,
) -> tuple[list[tuple[str | None, Mapping[str, Any]]], str | None]:
    """Return duplicate sample rows and the unanimous non‑null category (if any).

    IO is optimized by splitting work into:
    - an aggregate over matches to determine if all non‑null categories agree;
    - a limited sample (``exemplars``) of rows for display.
    """

    conds = []
    if group_eids:
        conds.append(FaTransaction.external_id.in_(group_eids))
    if group_fps:
        conds.append(FaTransaction.fingerprint_sha256.in_(group_fps))

    rows: list[tuple[str | None, Mapping[str, Any]]] = []
    unanimous: str | None = None
    if conds:
        base_filters = (
            (FaTransaction.source_provider == source_provider),
            (FaTransaction.source_account == source_account),
            or_(*conds),
        )

        # Aggregate: count distinct non‑null categories among matches
        agg_stmt = (
            select(func.count(distinct(FaTransaction.category)))
            .where(*base_filters)
            .where(FaTransaction.category.is_not(None))
        )
        distinct_count = session.execute(agg_stmt).scalar_one()
        if distinct_count == 1:
            # Fetch the single category value
            unanimous = session.execute(
                select(FaTransaction.category)
                .where(*base_filters)
                .where(FaTransaction.category.is_not(None))
                .limit(1)
            ).scalar_one()

        # Fetch a limited sample for display
        rows_stmt = (
            select(FaTransaction.category, FaTransaction.raw_record)
            .where(*base_filters)
            .limit(exemplars)
        )
        rows = [(row[0], row[1]) for row in session.execute(rows_stmt).all()]

    return rows, unanimous


# Closed set of allowed sources recorded with category updates
_ALLOWED_CATEGORY_SOURCES: set[str] = {"manual", "rule"}


def persist_group(
    session: Session,
    *,
    source_provider: str,
    source_account: str | None,
    group_items: Iterable[PreparedItem],
    final_cat: str,
    category_source: str = "manual",  # {"manual", "rule"}
    display_name: str | None = None,
) -> None:
    """Upsert group transactions and set ``category`` and metadata.

    Performs a batched update across the union of identifiers (external ids and
    fingerprints) within the provider/account scope. The caller is responsible
    for committing the transaction.
    """

    if category_source not in _ALLOWED_CATEGORY_SOURCES:
        raise ValueError(
            f"Unsupported category_source: {category_source!r}. "
            f"Allowed: {sorted(_ALLOWED_CATEGORY_SOURCES)}"
        )

    items = list(group_items)
    if not items:
        return

    # Ensure rows exist before updates
    upsert_transactions(
        session,
        source_provider=source_provider,
        source_account=source_account,
        transactions=[it.tx for it in items],
    )

    now = func.now()
    eids = [p.external_id for p in items if p.external_id is not None]
    # Use all fingerprints; do not exclude ones that also have an external_id
    fps = [p.fingerprint for p in items]

    base = update(FaTransaction).where(FaTransaction.source_provider == source_provider)
    if source_account is None:
        base = base.where(FaTransaction.source_account.is_(None))
    else:
        base = base.where(FaTransaction.source_account == source_account)

    values: dict[str, Any] = {
        "category": final_cat,
        "category_source": category_source,
        "category_confidence": None,
        "categorized_at": now,
        "verified": True,
        "updated_at": now,
    }
    if display_name is not None and display_name.strip():
        values.update(
            {
                "display_name": display_name.strip(),
                "display_name_source": "manual",
                "renamed_at": now,
            }
        )

    conds = []
    if eids:
        conds.append(FaTransaction.external_id.in_(eids))
    if fps:
        conds.append(FaTransaction.fingerprint_sha256.in_(fps))
    if conds:
        session.execute(base.where(or_(*conds)).values(**values))


__all__ = [
    "PreparedItem",
    "query_group_duplicates",
    "persist_group",
]
