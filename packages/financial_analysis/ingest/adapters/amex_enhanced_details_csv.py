"""Adapter for American Express "Enhanced Details" CSV exports with preamble.

This adapter locates the real CSV header within files that include one or more
human‑readable preamble lines above the column header, then delegates row → CTV
mapping to the existing AmEx‑like adapter to keep normalization identical.

Contract
--------
- The real header row must match exactly (after stripping the line ending):

  ``Date, Description, Card Member, Account #, Amount, Extended Details,``
  ``Appears On Your Statement As, Address, City/State, Zip Code, Country,``
  ``Reference, Category``

- Required columns (exact names) that must be present once the header is
  found:
  ``{"Date", "Description", "Amount", "Extended Details",``
  ``"Appears On Your Statement As", "Reference"}``

- Output CTV objects have the same shape and normalization as
  :mod:`packages.financial_analysis.ingest.adapters.amex_like_csv`:
  keys: ``idx, id, description, amount, date, merchant, memo``.

Failure mode
------------
If the header cannot be located or required columns are missing, a
``csv.Error`` is raised with a clear, actionable message. The CLI already
surfaces ``csv.Error`` as a parse failure without altering its error-handling
contract.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Iterator, Mapping
from typing import Any, TextIO

# Reuse the row → CTV mapping/normalization from the AmEx-like adapter
from .amex_like_csv import to_ctv as _to_ctv_like

# The exact header observed in user input (and required by this adapter)
EXACT_HEADER = (
    "Date,Description,Card Member,Account #,Amount,Extended Details,"
    "Appears On Your Statement As,Address,City/State,Zip Code,Country,"
    "Reference,Category"
)


# Columns that must be present for mapping to CTV
REQUIRED_COLUMNS: set[str] = {
    "Date",
    "Description",
    "Amount",
    "Extended Details",
    "Appears On Your Statement As",
    "Reference",
}


def _slice_from_header(text: str) -> io.StringIO:
    """Return a text stream positioned at the first occurrence of the real header.

    This function preserves the original content from the header line onward
    (including embedded newlines within quoted fields) by reconstructing the
    substring starting at the header line with original line endings intact.

    Raises ``csv.Error`` if the header cannot be located.
    """

    # Keep original newlines so CSV quoted newlines remain intact when rejoined
    lines = text.splitlines(keepends=True)
    for idx, line in enumerate(lines):
        if line.strip() == EXACT_HEADER:
            # Reconstruct the remainder exactly as in the original file
            remainder = "".join(lines[idx:])
            return io.StringIO(remainder)

    raise csv.Error(
        "AmEx Enhanced Details: could not locate the real header row. "
        "Expected a line that equals: " + EXACT_HEADER
    )


def _dict_reader_from_text(text: str) -> csv.DictReader:
    """Build a ``csv.DictReader`` starting at the real header inside ``text``.

    Validates that the required columns are present and raises ``csv.Error``
    with details when they are not.
    """

    stream = _slice_from_header(text)
    reader = csv.DictReader(stream)
    headers = reader.fieldnames
    if headers is None:
        raise csv.Error(
            "AmEx Enhanced Details: header row missing after preamble; file may be empty."
        )

    missing = sorted(col for col in REQUIRED_COLUMNS if col not in headers)
    if missing:
        raise csv.Error(
            "AmEx Enhanced Details: CSV header mismatch. Missing columns: " + ", ".join(missing)
        )

    return reader


def to_ctv_enhanced_details(file: TextIO) -> Iterator[Mapping[str, Any]]:
    """Convert an AmEx Enhanced Details CSV (with preamble) to CTV items.

    Parameters
    ----------
    file:
        An open text file object (``encoding='utf-8'``, ``newline=''``) for the
        AmEx Enhanced Details CSV export.

    Returns
    -------
    Iterator[Mapping[str, Any]]
        Iterator of CTV mapping objects with keys ``idx, id, description,
        amount, date, merchant, memo`` in input order.
    """

    text = file.read()
    reader = _dict_reader_from_text(text)
    # Delegate row → CTV mapping to the AmEx-like adapter for consistent
    # normalization and field semantics.
    return _to_ctv_like(reader)


def to_ctv_enhanced_details_from_path(path: str) -> Iterable[Mapping[str, Any]]:
    """Convenience wrapper that opens ``path`` and yields CTV items.

    This helper is not used by the CLI, but is provided for library callers.
    """

    with open(path, encoding="utf-8", newline="") as f:
        yield from to_ctv_enhanced_details(f)
