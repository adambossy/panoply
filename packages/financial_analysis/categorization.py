"""Input validation and result parsing for categorization.

This module intentionally does not define any taxonomy constants. Callers pass
the current two‑level taxonomy to the public API; callers of this module's
helpers derive a flat allow‑list of codes from that taxonomy for strict
validation of model outputs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# Prefer Pydantic for shape/typing validation to avoid manual isinstance chains.
from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

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


class _DetailItem(BaseModel):
    """Typed view of a single detailed categorization result.

    The validators rely on ``ValidationInfo.context`` to receive:
      - ``allowed_set``: set[str] of allowed categories
      - ``fallback_to_other``: bool indicating whether to coerce out-of-taxonomy
        values to ``Other``/``Unknown`` (when present in the allow-list)
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    idx: int
    id: str | None = None
    category: str
    rationale: str
    score: float
    revised_category: str | None = None
    revised_rationale: str | None = None
    revised_score: float | None = None
    citations: list[str] | None = None

    @field_validator("category", "revised_category")
    @classmethod
    def _category_in_allowlist(cls, v: str | None, info: ValidationInfo) -> str | None:
        if v is None:
            return None
        allowed_set = info.context.get("allowed_set") if info.context else None
        fallback_to_other = bool(info.context.get("fallback_to_other")) if info.context else True
        s = v.strip()
        if not allowed_set or s in allowed_set:
            return s
        if not fallback_to_other:
            raise ValueError(f"category not in allow-list: {s!r}")
        # Fallback stays within taxonomy when possible
        if "Other" in allowed_set:
            return "Other"
        if "Unknown" in allowed_set:
            return "Unknown"
        raise ValueError(f"category not in allow-list and no fallback available: {s!r}")

    @field_validator("rationale")
    @classmethod
    def _rationale_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("rationale must be a non-empty string")
        return v.strip()

    @field_validator("score", "revised_score")
    @classmethod
    def _score_in_range(cls, v: float | None) -> float | None:
        if v is None:
            return None
        if 0.0 <= float(v) <= 1.0:
            return float(v)
        raise ValueError("score must be in [0,1]")

    @field_validator("id")
    @classmethod
    def _normalize_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        return s or None

    @field_validator("citations")
    @classmethod
    def _normalize_citations(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        cleaned = [c.strip() for c in v if isinstance(c, str) and c.strip()]
        return cleaned or None


class _DetailBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[_DetailItem]


def parse_and_align_category_details(
    body: Mapping[str, Any],
    *,
    num_items: int,
    allowed_categories: Sequence[str],
    fallback_to_other: bool = True,
) -> list[dict[str, Any]]:
    """Parse Results with Pydantic and align by page-relative ``idx``.

    This reduces manual ``isinstance`` checks by delegating field validation and
    normalization to Pydantic models. It enforces required fields declared in
    the response schema (``id``, ``category``, ``rationale``, ``score``) and
    keeps numbers within [0,1]. Categories are validated against the provided
    allow‑list with an optional in‑taxonomy fallback to ``Other``/``Unknown``.
    """

    if not isinstance(body, Mapping):
        raise ValueError("Invalid response: expected a JSON object at top level")

    allowed_set = set(allowed_categories)
    parsed = _DetailBody.model_validate(
        body,
        context={"allowed_set": allowed_set, "fallback_to_other": fallback_to_other},
    )
    if len(parsed.results) != num_items:
        raise ValueError(
            f"Invalid response: expected {num_items} results, got {len(parsed.results)}"
        )

    out: list[dict[str, Any] | None] = [None] * num_items
    for item in parsed.results:
        idx = item.idx
        if not (0 <= idx < num_items):
            raise ValueError(f"Invalid response: 'idx' out of range: {idx}")
        if out[idx] is not None:
            raise ValueError(f"Invalid response: duplicate idx {idx}")
        out[idx] = {
            "idx": item.idx,
            "id": item.id,
            "category": item.category,
            "rationale": item.rationale,
            "score": item.score,
            "revised_category": item.revised_category,
            "revised_rationale": item.revised_rationale,
            "revised_score": item.revised_score,
            "citations": item.citations,
        }

    missing = [i for i, v in enumerate(out) if v is None]
    if missing:
        raise ValueError(f"Invalid response: missing indices {missing}")
    return [d for d in out if d is not None]
