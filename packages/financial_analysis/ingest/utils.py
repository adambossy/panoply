"""Ingest utilities shared by CLI commands and workflows.

Currently exposes a single helper to load Canonical Transaction View (CTV)
rows from an AmEx-like CSV, preferring the "Enhanced Details" adapter when
the file contains that header (even when preceded by a preamble).
"""

from __future__ import annotations

from collections.abc import Mapping
from os import PathLike
from pathlib import Path
from typing import Any


def load_ctv_from_amex_csv(csv_path: str | PathLike[str]) -> list[Mapping[str, Any]]:
    """Read an AmEx-like CSV and return Canonical Transaction View rows.

    Detection strategy:
    - Scan a small prefix for the "Extended Details" token to prefer the
      Enhanced Details adapter, which tolerates a preamble before the header.
    - Fallback to the standard AmEx-like adapter with strict header checks.
    """

    import csv

    from ..ingest.adapters.amex_enhanced_details_csv import (
        to_ctv_enhanced_details,
    )
    from ..ingest.adapters.amex_like_csv import to_ctv as to_ctv_standard

    p = Path(csv_path)
    with p.open(encoding="utf-8", newline="") as f:
        head = f.read(8192)
        f.seek(0)
        if "Extended Details" in head:
            return list(to_ctv_enhanced_details(f))

        reader = csv.DictReader(f)
        headers_set = set(reader.fieldnames or [])
        if not headers_set:
            raise csv.Error(f"CSV appears to have no header row: {csv_path}")
        required_headers = {
            "Reference",
            "Description",
            "Amount",
            "Date",
            "Appears On Your Statement As",
        }
        missing = sorted(h for h in required_headers if h not in headers_set)
        if missing:
            raise csv.Error(
                "CSV header mismatch for AmEx-like adapter. Missing columns: " + ", ".join(missing)
            )
        return list(to_ctv_standard(reader))


__all__ = ["load_ctv_from_amex_csv"]
