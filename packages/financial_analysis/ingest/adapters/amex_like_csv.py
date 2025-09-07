"""Adapter for mapping an AmEx-like CSV export to Canonical Transaction View.

CSV header (exact keys expected):
Date, Description, Card Member, Account #, Amount, Extended Details,
Appears On Your Statement As, Address, City/State, Zip Code, Country,
Reference, Category

Output CTV dict keys (exact order when serialized):
``idx, id, description, amount, date, merchant, memo``
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime
from typing import Any


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    # Replace internal newlines with spaces, collapse whitespace, and strip.
    cleaned = re.sub(r"\s+", " ", value.replace("\r", " ").replace("\n", " ")).strip()
    return cleaned if cleaned != "" else None


def _normalize_date(value: str | None) -> str | None:
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None
    # Attempt MM/DD/YYYY first; fall back to MM/DD/YY.
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            dt = datetime.strptime(s, fmt).date()
            return dt.isoformat()
        except ValueError:
            continue
    return None


def to_ctv(rows: Iterable[Mapping[str, str]]) -> Iterator[Mapping[str, Any]]:
    """Convert AmEx-like CSV rows to CTV dicts.

    Mapping rules:
    - ``idx``: sequential 0..N-1 by input order
    - ``id``: ``Reference`` (string) or ``None`` if missing/empty
    - ``description``: ``Description`` (normalized)
    - ``amount``: ``Amount`` (string) as-is after trimming
    - ``date``: normalized to YYYY-MM-DD when parseable; else ``None``
    - ``merchant``: ``Appears On Your Statement As`` (normalized)
    - ``memo``: ``Extended Details`` (normalized)
    """

    for idx, row in enumerate(rows):
        id_raw = row.get("Reference")
        description_raw = row.get("Description")
        amount_raw = row.get("Amount")
        date_raw = row.get("Date")
        merchant_raw = row.get("Appears On Your Statement As")
        memo_raw = row.get("Extended Details")

        yield {
            "idx": idx,
            "id": (id_raw.strip() if id_raw and id_raw.strip() != "" else None),
            "description": _clean_text(description_raw),
            "amount": (amount_raw.strip() if amount_raw is not None else None),
            "date": _normalize_date(date_raw),
            "merchant": _clean_text(merchant_raw),
            "memo": _clean_text(memo_raw),
        }
