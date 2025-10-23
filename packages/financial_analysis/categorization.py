"""Input validation and result parsing for categorization.

This module intentionally does not define any taxonomy constants. Callers pass
the current two‑level taxonomy to the public API; callers of this module's
helpers derive a flat allow‑list of codes from that taxonomy for strict
validation of model outputs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# ---------------------------------------------------------------------------
# Input validation (pre-request)
# ---------------------------------------------------------------------------


def ensure_valid_ctv_descriptions(ctv_items: Sequence[Mapping[str, Any]]) -> None:
    """Validate that each CTV item has a non-empty ``description`` after trimming.

    Raises ``ValueError`` on the first offending item. Error message includes
    the ``idx`` (if present/derivable) and ``id`` fields to aid debugging.
    """

    for pos, item in enumerate(ctv_items):
        desc = item.get("description")
        idx = item.get("idx", pos)
        tid = item.get("id")
        if not isinstance(desc, str) or len(desc.strip()) == 0:
            raise ValueError(f"Invalid input: description missing/empty for idx {idx} (id={tid!r})")


# ---------------------------------------------------------------------------
# Response parsing and alignment
# ---------------------------------------------------------------------------


def parse_and_align_categories(
    body: Mapping[str, Any],
    *,
    num_items: int,
    allowed_categories: Sequence[str],
    fallback_to_other: bool = True,
) -> list[str]:
    """Parse the Responses API JSON and return categories aligned by ``idx``.

    Expectations per spec:
    - ``body`` is a mapping containing a top-level key ``"results"`` whose
      value is a list of length ``num_items``.
    - Each element has ``idx`` (int), ``id`` (str | None), and ``category``
      (str). ``category`` must be within the provided ``allowed_categories``.
    - Alignment is by ``idx``; duplicates or missing indices are invalid.

    If a ``category`` value is not allowed and ``fallback_to_other`` is True,
    it is replaced with ``"Other"``; otherwise a ``ValueError`` is raised.
    """

    if not isinstance(body, Mapping):
        raise ValueError("Invalid response: expected a JSON object at top level")

    results = body.get("results")
    if not isinstance(results, list):
        raise ValueError("Invalid response: missing or non-list 'results'")
    if len(results) != num_items:
        raise ValueError(f"Invalid response: expected {num_items} results, got {len(results)}")

    categories_by_idx: list[str | None] = [None] * num_items
    # Resolve allow‑set for validation
    allowed_set = set(allowed_categories)

    for item in results:
        if not isinstance(item, Mapping):
            raise ValueError("Invalid response: each result must be an object")
        idx = item.get("idx")
        if not isinstance(idx, int):
            raise ValueError("Invalid response: 'idx' must be an integer")
        if idx < 0 or idx >= num_items:
            raise ValueError(f"Invalid response: 'idx' out of range: {idx}")
        if categories_by_idx[idx] is not None:
            raise ValueError(f"Invalid response: duplicate idx {idx}")

        cat_raw = item.get("category")
        if not isinstance(cat_raw, str):
            raise ValueError("Invalid response: 'category' must be a string")
        cat = cat_raw.strip()
        if cat not in allowed_set:
            if fallback_to_other:
                # Keep fallback within the provided taxonomy
                if "Other" in allowed_set:
                    cat = "Other"
                elif "Unknown" in allowed_set:
                    cat = "Unknown"
                else:
                    raise ValueError(
                        f"Invalid category and no in-taxonomy fallback available: {cat_raw!r}"
                    )
            else:
                raise ValueError(f"Invalid category value: {cat_raw!r}")

        categories_by_idx[idx] = cat

    # Ensure all slots were filled exactly once.
    missing = [i for i, v in enumerate(categories_by_idx) if v is None]
    if missing:
        raise ValueError(f"Invalid response: missing indices {missing}")

    return [c for c in categories_by_idx if c is not None]


def parse_and_align_category_details(
    body: Mapping[str, Any],
    *,
    num_items: int,
    allowed_categories: Sequence[str],
    fallback_to_other: bool = True,
) -> list[dict[str, Any]]:
    """Parse Responses JSON into aligned per-item dicts with details.

    Expected shape (strict):
    - body.results: list of length ``num_items``.
    - each item: { idx:int, id:str|null, category:str, rationale:str, score:number[0,1],
      revised_category?:str, revised_rationale?:str, revised_score?:number[0,1], citations?:str[] }

    Returns a list of length ``num_items`` ordered by page-relative ``idx``. All
    string values are trimmed. ``category`` and ``revised_category`` are
    validated against ``allowed_categories``; invalid values fall back to
    ``Other``/``Unknown`` when ``fallback_to_other`` is True, else a
    ``ValueError`` is raised.
    """

    if not isinstance(body, Mapping):
        raise ValueError("Invalid response: expected a JSON object at top level")

    results = body.get("results")
    if not isinstance(results, list):
        raise ValueError("Invalid response: missing or non-list 'results'")
    if len(results) != num_items:
        raise ValueError(f"Invalid response: expected {num_items} results, got {len(results)}")

    allowed_set = set(allowed_categories)
    out: list[dict[str, Any] | None] = [None] * num_items

    def _normalize_cat(raw: Any) -> str:
        if not isinstance(raw, str):
            raise ValueError("Invalid response: category must be string")
        v = raw.strip()
        if v in allowed_set:
            return v
        if not fallback_to_other:
            raise ValueError(f"Invalid category value: {raw!r}")
        if "Other" in allowed_set:
            return "Other"
        if "Unknown" in allowed_set:
            return "Unknown"
        raise ValueError(f"Invalid category and no fallback available: {raw!r}")

    for item in results:
        if not isinstance(item, Mapping):
            raise ValueError("Invalid response: each result must be an object")
        idx = item.get("idx")
        if not isinstance(idx, int):
            raise ValueError("Invalid response: 'idx' must be an integer")
        if idx < 0 or idx >= num_items:
            raise ValueError(f"Invalid response: 'idx' out of range: {idx}")
        if out[idx] is not None:
            raise ValueError(f"Invalid response: duplicate idx {idx}")

        cat = _normalize_cat(item.get("category"))
        # Required rationale and score
        rationale = item.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("Invalid response: 'rationale' must be a non-empty string")
        score = item.get("score")
        if not (isinstance(score, int | float) and 0 <= float(score) <= 1):
            raise ValueError("Invalid response: 'score' must be a number in [0,1]")

        # Optional revised_* and citations
        revised_category_raw = item.get("revised_category")
        revised_category: str | None
        if revised_category_raw is None:
            revised_category = None
        else:
            revised_category = _normalize_cat(revised_category_raw)
        revised_rationale_raw = item.get("revised_rationale")
        revised_rationale = (
            str(revised_rationale_raw).strip() if isinstance(revised_rationale_raw, str) else None
        )
        revised_score_raw = item.get("revised_score")
        revised_score: float | None
        if revised_score_raw is None:
            revised_score = None
        else:
            if not (
                isinstance(revised_score_raw, int | float) and 0 <= float(revised_score_raw) <= 1
            ):
                raise ValueError("Invalid response: 'revised_score' must be a number in [0,1]")
            revised_score = float(revised_score_raw)

        citations_raw = item.get("citations")
        citations: list[str] | None = None
        if citations_raw is not None:
            if not isinstance(citations_raw, list) or not all(
                isinstance(x, str) and x.strip() for x in citations_raw
            ):
                raise ValueError("Invalid response: 'citations' must be an array of strings")
            citations = [str(x).strip() for x in citations_raw]

        out[idx] = {
            "idx": idx,
            "id": item.get("id"),
            "category": cat,
            "rationale": rationale.strip(),
            "score": float(score),
            "revised_category": revised_category,
            "revised_rationale": revised_rationale,
            "revised_score": revised_score,
            "citations": citations,
        }

    missing = [i for i, v in enumerate(out) if v is None]
    if missing:
        raise ValueError(f"Invalid response: missing indices {missing}")
    return [d for d in out if d is not None]
