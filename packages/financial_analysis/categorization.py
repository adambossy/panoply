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
    """Lightweight parser that aligns detailed results by ``idx``.

    This intentionally focuses on the happy path: a top-level mapping with a
    ``results`` list of length ``num_items`` where each element contains
    ``idx``, ``category``, and optional detail fields. We rely on the strict
    JSON schema given to the model to keep shapes sane and avoid guarding every
    edge case here. Categories not in ``allowed_categories`` are replaced with
    ``Other`` (or ``Unknown``) when ``fallback_to_other`` is True.
    """

    if not isinstance(body, Mapping):
        raise ValueError("Invalid response: expected a JSON object at top level")

    results = body.get("results")
    if not isinstance(results, list) or len(results) != num_items:
        raise ValueError(f"Invalid response: expected 'results' list of length {num_items}")

    allowed_set = set(allowed_categories)
    out: list[dict[str, Any] | None] = [None] * num_items

    def _cat(v: Any) -> str:
        # Always return a valid category from the allow-list or raise.
        if not isinstance(v, str):
            if fallback_to_other:
                if "Other" in allowed_set:
                    return "Other"
                if "Unknown" in allowed_set:
                    return "Unknown"
            raise ValueError("Invalid response: category must be a string")
        s = v.strip()
        if s in allowed_set:
            return s
        if fallback_to_other:
            if "Other" in allowed_set:
                return "Other"
            if "Unknown" in allowed_set:
                return "Unknown"
        raise ValueError(f"Invalid category value: {v!r} and no fallback available")

    for item in results:
        if not isinstance(item, Mapping):
            raise ValueError("Invalid response: each result must be an object")
        idx = item.get("idx")
        if not isinstance(idx, int) or not (0 <= idx < num_items):
            raise ValueError(f"Invalid response: 'idx' out of range: {idx}")
        if out[idx] is not None:
            raise ValueError(f"Invalid response: duplicate idx {idx}")

        cat = _cat(item.get("category"))
        revised_cat_raw = item.get("revised_category")
        revised_cat = _cat(revised_cat_raw) if isinstance(revised_cat_raw, str) else None

        # Trim simple string fields; tolerate absence
        def _t(s: Any) -> str | None:
            return s.strip() if isinstance(s, str) and s.strip() else None

        citations_val = item.get("citations")
        citations: list[str] | None = None
        if isinstance(citations_val, list):
            citations = [c.strip() for c in citations_val if isinstance(c, str) and c.strip()]
            if not citations:
                citations = None

        # Coerce numeric scores when present; keep them within [0,1]
        def _num01(x: Any, field: str) -> float | None:
            if isinstance(x, int | float):
                xf = float(x)
                if 0.0 <= xf <= 1.0:
                    return xf
                raise ValueError(f"Invalid response: '{field}' must be a number in [0,1]")
            return None

        score_num = _num01(item.get("score"), "score")
        revised_score_num = _num01(item.get("revised_score"), "revised_score")

        # Normalize id to a string or None
        _id = item.get("id")
        id_out = _t(_id) if isinstance(_id, str) else None

        out[idx] = {
            "idx": idx,
            "id": id_out,
            "category": cat,
            "rationale": _t(item.get("rationale")),
            "score": score_num,
            "revised_category": revised_cat,
            "revised_rationale": _t(item.get("revised_rationale")),
            "revised_score": revised_score_num,
            "citations": citations,
        }

    missing = [i for i, v in enumerate(out) if v is None]
    if missing:
        raise ValueError(f"Invalid response: missing indices {missing}")
    return [d for d in out if d is not None]
