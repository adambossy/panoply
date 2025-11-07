# ruff: noqa: I001
"""Workflow orchestrators for end-to-end review flows.

This module houses high-level functions that compose ingest, categorization,
and the interactive review UI behind a single importable API. Keeping this code
out of ``api.py`` maintains a light import surface while allowing ``api`` to
re‑export stable entry points.
"""

from __future__ import annotations

from collections.abc import Callable
from os import PathLike

from ..ingest.utils import load_ctv_from_amex_csv
from ..models import CategorizedTransaction
from ..pre_review import prepare_pre_review
from ..review import review_transaction_categories


def review_categories_from_csv(
    csv_path: str | PathLike[str],
    *,
    database_url: str | None = None,
    source_provider: str = "amex",
    source_account: str | None = None,
    allow_create: bool | None = None,
    on_progress: Callable[[str], None] | None = None,
    min_confidence: float = 0.7,
) -> list[CategorizedTransaction]:
    """End-to-end: CSV → CTV → prefill → categorize unresolved → review+persist.

    Parameters
    ----------
    csv_path:
        Path to an AmEx-like CSV export.
    database_url:
        Optional DB URL override. Falls back to ``DATABASE_URL`` when ``None``.
    source_provider / source_account:
        Scope for persistence and duplicate lookups.
    allow_create:
        When ``True`` (default), the review UI allows creating a new category
        during selection. ``None`` preserves the upstream default.
    on_progress:
        Optional callable to receive short status lines (e.g., ``print``).

    Returns
    -------
    list[CategorizedTransaction]
        The finalized items returned by the interactive review. This list
        contains the unresolved subset only; groups auto‑applied from the DB
        prefill step are persisted but not included in the returned list.
    """

    # CSV → CTV
    ctv_items = load_ctv_from_amex_csv(str(csv_path))
    if not ctv_items:
        if on_progress:
            on_progress("No transactions to review.")
        return []

    # Pre-review orchestration (persist DB prefill + auto-apply in review path)
    ctx = prepare_pre_review(
        ctv_items,
        database_url=database_url,
        source_provider=source_provider,
        source_account=source_account,
        persist_db_prefill=True,
        persist_auto_apply=True,
        min_confidence=min_confidence,
    )

    if on_progress and ctx.prefill.groups_count:
        on_progress(f"Auto-prefilled {ctx.prefill.groups_count} group(s) from DB.")
    if on_progress and ctx.auto_applied_count:
        on_progress(
            "Auto-applied "
            f"{ctx.auto_applied_count} high-confidence suggestions (> {min_confidence})."
        )
    if on_progress and ctx.unresolved_ctv:
        on_progress(f"Categorizing {len(ctx.unresolved_ctv)} unresolved items…")

    # Short-circuit when there is nothing left to review
    if not ctx.unresolved_suggestions:
        return review_transaction_categories(
            [],
            source_provider=source_provider,
            source_account=source_account,
            database_url=database_url,
            prefilled_groups=ctx.prefill.groups_count,
            allow_create=allow_create,
        )

    # Interactive review of the low-confidence remainder
    return review_transaction_categories(
        ctx.unresolved_suggestions,
        source_provider=source_provider,
        source_account=source_account,
        database_url=database_url,
        prefilled_groups=ctx.prefill.groups_count,
        allow_create=allow_create,
    )


__all__ = ["review_categories_from_csv"]
