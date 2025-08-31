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
    """A transaction paired with an assigned category.

    Attributes
    ----------
    transaction:
        The original transaction record (opaque mapping of CSV columns).
    category:
        The assigned category label. The category ontology, normalization
        rules, and allowed values are not defined here and will require
        clarification (e.g., hierarchical categories, canonical casing).
    """

    transaction: TransactionRecord
    category: str


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
