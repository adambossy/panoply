from __future__ import annotations

# Seeder for the two-level transaction category taxonomy.
#
# Usage (example):
#   uv run python -m financial_analysis.ingest.seed_taxonomy \
#     --database-url postgresql://user:pass@host:5432/db \
#     --file packages/financial_analysis/ingest/seeds/fa_taxonomy.v1.json
#
# This script:
#   1) Truncates fa_categories (CASCADE) and reseeds the taxonomy (parents
#      first, then children with parent_code set), preserving input order via
#      sort_order.
#   2) Leaves fa_transactions.category as-is (migration 0002 clears it once).
import argparse
import json
from pathlib import Path
from typing import Any

from db.client import session_scope
from db.models.finance import FaCategory
from sqlalchemy import text


def _load_json(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Seed JSON must be a list of parent categories")
    return data


def reseed_taxonomy(*, database_url: str | None, file: Path) -> None:
    data = _load_json(file)
    with session_scope(database_url=database_url) as session:
        # Destructive reset acceptable pre-launch
        session.execute(text("TRUNCATE TABLE fa_categories CASCADE"))

        # Insert parents first
        order = 0
        for parent in data:
            code = str(parent.get("code") or parent.get("display_name"))
            name = str(parent.get("display_name") or code)
            row = FaCategory(
                code=code,
                display_name=name,
                parent_code=None,
                is_active=True,
                sort_order=order,
            )
            session.add(row)
            order += 1
        session.flush()

        # Map code -> code (simple in this schema); used for parent reference optionally
        parent_codes = {p.get("code"): p.get("code") for p in data}

        # Insert children, preserving per-parent order
        for parent_index, parent in enumerate(data):
            pcode = parent.get("code")
            for child_index, child in enumerate(parent.get("children", []) or []):
                ccode = str(child.get("code") or child.get("display_name"))
                cname = str(child.get("display_name") or ccode)
                row = FaCategory(
                    code=ccode,
                    display_name=cname,
                    parent_code=parent_codes.get(pcode),
                    is_active=True,
                    sort_order=(parent_index * 100 + child_index),
                )
                session.add(row)
        session.flush()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Reseed the 2-level category taxonomy",
    )
    ap.add_argument(
        "--database-url",
        required=False,
        default=None,
        help=("SQLAlchemy database URL; falls back to $DATABASE_URL when not set"),
    )
    ap.add_argument(
        "--file",
        type=Path,
        required=False,
        default=Path("packages/financial_analysis/ingest/seeds/fa_taxonomy.v1.json"),
    )
    args = ap.parse_args(argv)

    db_url: str | None = args.database_url or None
    reseed_taxonomy(database_url=db_url, file=args.file)
    return 0


if __name__ == "__main__":  # pragma: no cover - manual utility
    raise SystemExit(main())
