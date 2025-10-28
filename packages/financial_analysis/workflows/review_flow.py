"""Workflow orchestrators for end-to-end review flows.

This module houses high-level functions that compose ingest, categorization,
and the interactive review UI behind a single importable API. Keeping this code
out of ``api.py`` maintains a light import surface while allowing ``api`` to
re‑export stable entry points.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from os import PathLike
from pathlib import Path
from typing import Any

from ..categories import load_taxonomy_from_db
from ..categorize import categorize_expenses, prefill_unanimous_groups_from_db
from ..models import CategorizedTransaction
from ..persistence import auto_persist_high_confidence
from ..review import review_transaction_categories


def _read_ctv_from_csv(csv_path: str | PathLike[str]) -> list[Mapping[str, Any]]:
    """Read an AmEx-like CSV and return Canonical Transaction View rows.

    Detection mirrors the existing CLI behavior:
    - Scan a small prefix for the "Extended Details" token to prefer the
      Enhanced Details adapter, which tolerates a preamble before the header.
    - Fallback to the standard AmEx-like adapter with strict header checks.
    """

    import csv

    from ..ingest.adapters.amex_enhanced_details_csv import (
        to_ctv_enhanced_details,
    )
    from ..ingest.adapters.amex_like_csv import to_ctv as to_ctv_standard

    p = Path(csv_path)
    with p.open(encoding="utf-8", newline="") as f:
        head = f.read(8192)
        f.seek(0)
        if "Extended Details" in head:
            return list(to_ctv_enhanced_details(f))

        reader = csv.DictReader(f)
        headers_set = set(reader.fieldnames or [])
        if not headers_set:
            raise csv.Error(f"CSV appears to have no header row: {csv_path}")
        required_headers = {
            "Reference",
            "Description",
            "Amount",
            "Date",
            "Appears On Your Statement As",
        }
        missing = sorted(h for h in required_headers if h not in headers_set)
        if missing:
            raise csv.Error(
                "CSV header mismatch for AmEx-like adapter. Missing columns: " + ", ".join(missing)
            )
        return list(to_ctv_standard(reader))


def review_categories_from_csv(
    csv_path: str | PathLike[str],
    *,
    database_url: str | None = None,
    source_provider: str = "amex",
    source_account: str | None = None,
    allow_create: bool | None = None,
    on_progress: Callable[[str], None] | None = None,
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
    ctv_items = _read_ctv_from_csv(str(csv_path))
    if on_progress:
        # Only print existing values: count and provided scope identifiers
        acct = source_account if source_account is not None else "-"
        on_progress(
            f"Parsed transactions: count={len(ctv_items)} provider={source_provider} account={acct}"
        )
    if not ctv_items:
        if on_progress:
            on_progress("No transactions to review.")
        return []

    # DB‑first prefill
    prefilled_positions, prefilled_groups = prefill_unanimous_groups_from_db(
        ctv_items,
        database_url=database_url,
        source_provider=source_provider,
        source_account=source_account,
    )
    if on_progress and (prefilled_groups or prefilled_positions):
        on_progress(
            "Prefill: groups_applied="
            f"{prefilled_groups} positions_assigned={len(prefilled_positions)}"
        )

    # Build unresolved subset in original order
    unresolved_indices: list[int] = [
        i for i in range(len(ctv_items)) if i not in prefilled_positions
    ]
    unresolved_ctv: list[Mapping[str, Any]] = [ctv_items[i] for i in unresolved_indices]

    # If everything resolved via DB, show the summary path and exit.
    if not unresolved_ctv:
        return review_transaction_categories(
            [],
            source_provider=source_provider,
            source_account=source_account,
            database_url=database_url,
            prefilled_groups=prefilled_groups,
            allow_create=allow_create,
        )

    # Taxonomy for schema + prompt context
    taxonomy = load_taxonomy_from_db(database_url=database_url)

    if on_progress:
        # Do not invent estimates; report only the unresolved size already known
        on_progress(f"LLM: unresolved_items={len(unresolved_ctv)}")

    # Categorize unresolved only (page cache keyed by dataset_id inside impl)
    suggestions = categorize_expenses(
        transactions=unresolved_ctv,
        taxonomy=taxonomy,
        source_provider=source_provider,
    )

    # Auto-apply high-confidence suggestions before entering the UI
    from db.client import session_scope  # local import to keep import-time light

    with session_scope(database_url=database_url) as session:
        applied = auto_persist_high_confidence(
            session,
            source_provider=source_provider,
            source_account=source_account,
            suggestions=suggestions,
            min_confidence=0.7,
        )
    if applied and on_progress:
        on_progress(f"Auto-applied {applied} high-confidence suggestions (> 0.7).")

    # Interactive review of the low-confidence remainder
    result = review_transaction_categories(
        suggestions,
        source_provider=source_provider,
        source_account=source_account,
        database_url=database_url,
        prefilled_groups=prefilled_groups,
        allow_create=allow_create,
    )
    if on_progress:
        on_progress(f"Done: prefilled_groups={prefilled_groups} auto_applied_items={applied or 0}")
    return result


__all__ = ["review_categories_from_csv"]
