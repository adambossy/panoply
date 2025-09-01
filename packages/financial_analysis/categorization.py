"""Result parsing, validation, and constants for categorization.

Implements:
- ``ALLOWED_CATEGORIES`` constant (single source of truth).
- Pre-request input validation for CTV items.
- Parsing/validation of the OpenAI Responses API JSON body and alignment of
  categories by ``idx`` back to the input order.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# ---------------------------------------------------------------------------
# Category whitelist (exact casing)
# ---------------------------------------------------------------------------

ALLOWED_CATEGORIES: tuple[str, ...] = (
    "Groceries",
    "Restaurants",
    "Coffee Shops",
    "Flights",
    "Hotels",
    "Clothing",
    "Shopping",
    "Baby",
    "House",
    "Pet",
    "Emergency",
    "Medical",
    "Other",
)

_ALLOWED_SET = set(ALLOWED_CATEGORIES)


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
    body: Mapping[str, Any], *, num_items: int, fallback_to_other: bool = True
) -> list[str]:
    """Parse the Responses API JSON and return categories aligned by ``idx``.

    Expectations per spec:
    - ``body`` is a mapping containing a top-level key ``"results"`` whose
      value is a list of length ``num_items``.
    - Each element has ``idx`` (int), ``id`` (str | None), and ``category``
      (str). ``category`` must be in :data:`ALLOWED_CATEGORIES`.
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
        if cat not in _ALLOWED_SET:
            if fallback_to_other:
                cat = "Other"
            else:
                raise ValueError(f"Invalid category value: {cat_raw!r}")

        categories_by_idx[idx] = cat

    # Ensure all slots were filled exactly once.
    missing = [i for i, v in enumerate(categories_by_idx) if v is None]
    if missing:
        raise ValueError(f"Invalid response: missing indices {missing}")

    return [c for c in categories_by_idx if c is not None]
