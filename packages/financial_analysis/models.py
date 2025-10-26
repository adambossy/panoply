"""Data models and type aliases for ``financial_analysis``.

This module intentionally avoids committing to a specific CSV schema. Names of
columns (e.g., date, amount, description, identifiers) and their formats are
unspecified and MUST be clarified before implementation. Types here are kept
opaque and generic to accommodate different bank-export formats.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, NamedTuple

from pydantic import BaseModel, ConfigDict, field_validator

# ---------------------------------------------------------------------------
# Core record and collections
# ---------------------------------------------------------------------------

# An opaque, mapping-like record that can hold arbitrary CSV columns. Keys are
# column names; values are raw cell values as loaded from CSV. This does not
# prescribe required columns or formats.
type TransactionRecord = Mapping[str, Any]
"""A single transaction row with arbitrary columns from a CSV export.

Notes
-----
- Required column names (e.g., date, amount, description, unique ID) are not
  specified here and require confirmation.
- Value types are not constrained; they may be strings from raw CSV parsing or
  parsed types (dates/decimals) depending on the eventual implementation.
"""


@dataclass(frozen=True, slots=True)
class CategorizedTransaction:
    """A transaction paired with an assigned (effective) category.

    ``category`` reflects the effective choice used by the application. When
    the model provides a post-search revision, ``revised_category`` is treated
    as authoritative and copied here for downstream flows. For observability,
    model-provided details (rationale/score and any post-search ``revised_*``
    fields, plus ``citations``) are carried directly on this model for each
    item. ``rationale`` and ``score`` are required and used downstream (e.g.,
    confidence gating before review).
    """

    transaction: TransactionRecord
    category: str
    # Required details provided by the model (or caller) for this decision.
    # These are required by the strict response schema and are used downstream
    # (e.g., pre‑review confidence gating). Callers creating instances outside
    # the LLM flow (e.g., rule/default assignments) must provide values.
    rationale: str
    score: float
    revised_category: str | None = None
    revised_rationale: str | None = None
    revised_score: float | None = None
    citations: tuple[str, ...] | None = None


class RefundMatch(NamedTuple):
    """An expense/refund pairing represented by full records, not indices.

    Each element is a :data:`TransactionRecord` drawn directly from the
    provided collection. This replaces earlier row-index based matching to
    avoid ambiguity about CSV row numbering and to make downstream processing
    simpler (no re-indexing/lookups required).

    Notes
    -----
    - The amount column name and its format (e.g., sign conventions, decimal
      precision, currency handling) are not specified.
    - Timezone, posting date vs transaction date, and any date parsing rules
      are not defined here.
    """

    expense: TransactionRecord
    """The original expense record from the input collection."""

    refund: TransactionRecord
    """The corresponding refund record from the input collection."""


# ---------------------------------------------------------------------------
# Partitioning period specification
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PartitionPeriod:
    """A structured period spec for partitioning transactions.

    All fields are optional and can be combined (they are not mutually
    exclusive). Values represent counts of calendar units to use when
    partitioning a sequence of transactions (e.g., ``months=1`` for monthly
    partitions, ``weeks=2`` for biweekly, or combinations like ``months=1,
    days=3``).

    Attributes
    ----------
    years:
        Optional number of years per partition.
    months:
        Optional number of months per partition.
    weeks:
        Optional number of weeks per partition.
    days:
        Optional number of days per partition.
    """

    years: int | None = None
    months: int | None = None
    weeks: int | None = None
    days: int | None = None

    def __post_init__(self) -> None:
        """Validate that at least one positive unit is provided.

        - At least one of ``years``, ``months``, ``weeks``, or ``days`` must
          be non-``None``.
        - Any provided value must be a positive integer (> 0).
        """

        values = {
            "years": self.years,
            "months": self.months,
            "weeks": self.weeks,
            "days": self.days,
        }

        if all(v is None for v in values.values()):
            raise ValueError(
                "PartitionPeriod requires at least one of years/months/weeks/days to be set"
            )

        for name, val in values.items():
            if val is None:
                continue
            # Enforce integer and positivity. Booleans are ints; disallow them explicitly.
            if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
                raise ValueError(f"PartitionPeriod.{name} must be a positive integer when set")


# Generic collections
type Transactions = Iterable[TransactionRecord]
"""A generic iterable of transaction records.

The element shape is intentionally opaque. Callers must agree on the CSV schema
externally; this package does not enforce column names or types.
"""

type TransactionPartitions = Iterable[Iterable[TransactionRecord]]
"""A generic iterable of transaction subsets (partitions).

The partitioning strategy and period semantics are unspecified here.
"""


# ---------------------------------------------------------------------------
# DTOs for typed page-cache I/O
# ---------------------------------------------------------------------------


class LlmDecision(BaseModel):
    """Typed, validated model of a single categorization decision.

    Mirrors the JSON written to the page cache (and produced by the parser in
    ``categorization.py``). Extras are allowed to preserve the current on-disk
    JSON shape (e.g., page-relative ``idx`` and optional ``id``) while keeping
    the typed API focused on decision fields.
    """

    model_config = ConfigDict(strict=True, extra="allow", str_strip_whitespace=True)

    category: str
    rationale: str
    score: float
    revised_category: str | None = None
    revised_rationale: str | None = None
    revised_score: float | None = None
    citations: tuple[str, ...] | None = None

    @field_validator("rationale")
    @classmethod
    def _rationale_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("rationale must be non-empty")
        return v

    @field_validator("score", "revised_score")
    @classmethod
    def _score_in_unit_interval(cls, v: float | None) -> float | None:
        if v is None:
            return None
        fv = float(v)
        if 0.0 <= fv <= 1.0:
            return fv
        raise ValueError("score must be within [0,1]")

    @field_validator("citations")
    @classmethod
    def _normalize_citations(
        cls, v: tuple[str, ...] | list[str] | None
    ) -> tuple[str, ...] | None:
        if v is None:
            return None
        items = [s.strip() for s in list(v) if isinstance(s, str) and s.strip()]
        return tuple(items) if items else None


class PageExemplar(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", str_strip_whitespace=True)
    abs_index: int
    fp: str


class PageItem(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    abs_index: int
    details: LlmDecision


class PageCacheFile(BaseModel):
    """Top-level schema for a page cache JSON file."""

    model_config = ConfigDict(strict=True, extra="forbid", str_strip_whitespace=True)

    # Metadata identifying the dataset and page
    schema_version: int
    dataset_id: str
    page_size: int
    page_index: int
    settings_hash: str

    # Payload: alignment and decision details
    exemplars: list[PageExemplar]
    items: list[PageItem]
