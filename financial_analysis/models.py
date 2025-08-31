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
    """A pair of row indices indicating an expense and its matching refund.

    This explicitly represents two indices into the original CSV rows: the
    expense row and the refund row. The indexing base (0-based vs 1-based) is
    intentionally left unspecified and MUST be clarified with stakeholders.

    Notes
    -----
    - The amount column name and its format (e.g., sign conventions, decimal
      precision, currency handling) are not specified.
    - Timezone, posting date vs transaction date, and any date parsing rules
      are not defined here.
    """

    expense_row_index: int
    refund_row_index: int


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
