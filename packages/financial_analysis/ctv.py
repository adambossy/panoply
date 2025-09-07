"""Canonical Transaction View (CTV) models and helpers.

This module defines the Canonical Transaction View record as a frozen
``dataclass`` with explicit field order and types, updated per the revised
spec to include a ``category`` field between ``merchant`` and ``memo``.

Field order (exact):
    - idx: integer (0-based position within the input collection after
      dropping non-transaction rows)
    - id: string | None
    - description: string | None
    - amount: string | None (normalized string, 2 decimal places, ASCII dot
      decimal, leading sign where negative)
    - date: string | None (YYYY-MM-DD)
    - merchant: string | None
    - category: string | None
    - memo: string | None
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CanonicalTransaction:
    """A single canonicalized transaction row.

    All fields are strings (or ``None``) to keep the view CSV/JSON-friendly and
    portable across systems. ``amount`` and ``date`` are represented as
    normalized strings rather than numeric/date types to preserve exact output
    formatting guarantees.
    """

    idx: int
    id: str | None
    description: str | None
    amount: str | None
    date: str | None
    merchant: str | None
    category: str | None
    memo: str | None


__all__ = ["CanonicalTransaction"]
