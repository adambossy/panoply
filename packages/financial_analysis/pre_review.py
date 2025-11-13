# ruff: noqa: I001
"""Shared pre-review orchestration used by both CLI commands and workflows.

This module centralizes the steps that occur before any interactive review:

1) DB-first prefill of unanimous duplicate groups (optional persist)
2) Taxonomy load from the database
3) LLM categorization of unresolved items only (page cache aware)
4) Optional auto-apply of high-confidence suggestions

It also provides a helper to materialize a complete ordered result set for
printing or persistence by merging the prefilled groups with LLM suggestions.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .categories import load_taxonomy_from_db
from .categorize import (
    categorize_expenses,
    prefill_unanimous_groups_from_db_with_map,
)
from .models import CategorizedTransaction


@dataclass(frozen=True, slots=True)
class PrefillResult:
    positions: set[int]
    groups_count: int
    category_by_pos: dict[int, str]


@dataclass(frozen=True, slots=True)
class PreReviewContext:
    ctv_items: list[Mapping[str, Any]]
    taxonomy: list[dict[str, Any]]
    prefill: PrefillResult
    unresolved_indices: list[int]
    unresolved_ctv: list[Mapping[str, Any]]
    unresolved_suggestions: list[CategorizedTransaction]
    auto_applied_count: int = 0


def prepare_pre_review(
    ctv_items: list[Mapping[str, Any]],
    *,
    database_url: str | None,
    source_provider: str,
    source_account: str | None,
    persist_db_prefill: bool,
    persist_auto_apply: bool,
    min_confidence: float = 0.7,
) -> PreReviewContext:
    """Compute shared pre-review artifacts and perform optional persistence.

    Returns a structured context with prefilled positions, unresolved subset,
    taxonomy, and LLM suggestions for unresolved items.
    """

    # 1) DB-first prefill (optionally persist)
    (
        prefilled_positions,
        prefilled_groups,
        category_by_pos,
    ) = prefill_unanimous_groups_from_db_with_map(
        ctv_items,
        database_url=database_url,
        source_provider=source_provider,
        source_account=source_account,
        persist=persist_db_prefill,
    )

    # 2) Build unresolved subset (preserve original order)
    unresolved_indices: list[int] = [
        i for i in range(len(ctv_items)) if i not in prefilled_positions
    ]
    unresolved_ctv: list[Mapping[str, Any]] = [ctv_items[i] for i in unresolved_indices]

    # 3) Load taxonomy exactly once for both schema and prompt context
    taxonomy = load_taxonomy_from_db(database_url=database_url)

    # 4) Categorize unresolved only
    suggestions: list[CategorizedTransaction] = []
    if unresolved_ctv:
        suggestions = categorize_expenses(
            transactions=unresolved_ctv,
            taxonomy=taxonomy,
            source_provider=source_provider,
        )

        # 5) Optional auto-apply of high-confidence suggestions
        auto_applied_count = 0
        if persist_auto_apply:
            from db.client import session_scope  # noqa: I001  (local import)
            from .persistence import auto_persist_high_confidence

            with session_scope(database_url=database_url) as session:
                auto_applied_count = auto_persist_high_confidence(
                    session,
                    source_provider=source_provider,
                    source_account=source_account,
                    suggestions=suggestions,
                    min_confidence=min_confidence,
                )

    return PreReviewContext(
        ctv_items=ctv_items,
        taxonomy=taxonomy,
        prefill=PrefillResult(
            positions=prefilled_positions,
            groups_count=prefilled_groups,
            category_by_pos=category_by_pos,
        ),
        unresolved_indices=unresolved_indices,
        unresolved_ctv=unresolved_ctv,
        unresolved_suggestions=suggestions,
        auto_applied_count=locals().get("auto_applied_count", 0),
    )


def materialize_final_results_for_print(ctx: PreReviewContext) -> list[CategorizedTransaction]:
    """Merge prefilled categories with LLM suggestions to one ordered list.

    For prefilled positions, synthesize a CategorizedTransaction with
    rationale='rule: unanimous dup' and score=1.0 to make thresholds explicit.
    """

    out: list[CategorizedTransaction | None] = [None] * len(ctx.ctv_items)

    # Prefilled first (explicit marker for downstream visibility)
    for pos, cat in ctx.prefill.category_by_pos.items():
        tx = ctx.ctv_items[pos]
        out[pos] = CategorizedTransaction(
            transaction=tx,
            category=cat,
            rationale="rule: unanimous dup",
            score=1.0,
        )

    # Suggestions align 1:1 with unresolved_indices in order
    for j, pos in enumerate(ctx.unresolved_indices):
        out[pos] = ctx.unresolved_suggestions[j]

    # Validate fill completeness
    missing = [i for i, v in enumerate(out) if v is None]
    if missing:
        raise RuntimeError(f"materialize_final_results_for_print: missing positions {missing}")

    # Type narrowing
    return [r for r in out if r is not None]


__all__ = [
    "PrefillResult",
    "PreReviewContext",
    "prepare_pre_review",
    "materialize_final_results_for_print",
]
