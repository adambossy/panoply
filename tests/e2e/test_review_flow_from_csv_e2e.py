# ruff: noqa: E402, I001
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# Make sure the workspace `packages/` dir is on sys.path so `financial_analysis` is importable
_ROOT = Path(__file__).resolve().parents[2]
_PKG_DIR = _ROOT / "packages"
sys.path[:0] = [p for p in [str(_PKG_DIR), str(_ROOT)] if p not in sys.path]

from db.client import session_scope  # noqa: E402
from db.models.finance import FaTransaction  # noqa: E402

from financial_analysis.api import review_categories_from_csv  # noqa: E402
import financial_analysis.categorize as categorize_mod  # noqa: E402

from tests.helpers.db import (  # noqa: E402
    bootstrap_sqlite_db,
    seed_full_taxonomy_from_json,
)
from tests.helpers.openai_stub import OpenAIStub  # noqa: E402


def _decide_category(item: dict[str, Any]) -> tuple[str, float, str]:
    """Deterministic mapping from a CTV item to (category, score, rationale).

    High-confidence scores (>0.7) ensure the workflow auto-applies these
    decisions to the database without invoking the interactive UI.
    """

    desc = (item.get("description") or "").upper()
    merch = (item.get("merchant") or "").upper()
    memo = (item.get("memo") or "").upper()
    text = f"{desc} {merch} {memo}"

    def pick(cat: str, why: str) -> tuple[str, float, str]:
        return cat, 0.92, why

    if "UBER" in text:
        return pick("Rides & Taxis", "ride")
    if "DOORDASH" in text or "DD *" in text:
        return pick("Delivery & Takeout", "delivery")
    if "RHYTHM ZERO" in text or "COFFEE" in text:
        return pick("Coffee Shops", "coffee")
    if "HELLOFRESH" in text:
        return pick("Meal Kits", "meal kit")
    if "MERCADO LA M" in text or "DELI POINT" in text or "JUBILEE MARKET" in text:
        return pick("Groceries", "groceries")
    if "KIJITORA" in text or "TIFFIN" in text or "LITTLE T" in text:
        return pick("Restaurants", "restaurant")
    if "ATELIER COUTU" in text or "ETSY" in text:
        return pick("Clothing & Accessories", "apparel")
    if "LULU AND GEORGIA" in text:
        return pick("Furniture & Appliances", "furnishing")
    if "ORKIN" in text:
        return pick("Home Services & Maintenance", "home svc")
    if "AMAZON" in text:
        return pick("Electronics & Gadgets", "shopping")
    return pick("Electronics & Gadgets", "default")


def test_e2e_review_categories_from_csv_persists_expected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    # -------------------------
    # Input (fixture file path)
    # -------------------------
    csv_path = Path(__file__).resolve().parents[1] / "data/amex_aug_24_29_2025_subset.csv"

    # -------------------------
    # DB bootstrap + taxonomy
    # -------------------------
    db_url = bootstrap_sqlite_db(tmp_path / "fa-e2e.db")
    seed_full_taxonomy_from_json(
        database_url=db_url,
        json_path=_ROOT / "packages/financial_analysis/ingest/seeds/fa_taxonomy.v1.json",
    )

    # -------------------------
    # Stub the OpenAI client used inside categorize.py
    # -------------------------
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(categorize_mod, "OpenAI", lambda: OpenAIStub(_decide_category, calls))

    # -------------------------
    # Execute the end-to-end workflow (twice to assert idempotency)
    # -------------------------
    _ = review_categories_from_csv(
        csv_path,
        database_url=db_url,
        source_provider="amex",
        source_account=None,
        allow_create=False,
        on_progress=lambda s: None,  # keep test output clean
    )
    _ = review_categories_from_csv(
        csv_path,
        database_url=db_url,
        source_provider="amex",
        source_account=None,
        allow_create=False,
        on_progress=lambda s: None,  # keep test output clean
    )

    # -------------------------
    # Expected outputs (external_id -> category)
    # -------------------------
    expected = {
        # 2025-08-29
        "320252410422442649": "Rides & Taxis",  # UBER
        # 2025-08-28
        "320252400412664970": "Electronics & Gadgets",  # AMAZON.COM
        "320252400395259948": "Delivery & Takeout",  # DOORDASH
        "320252400390297709": "Groceries",  # MERCADO LA MERCED
        "320252400397637017": "Coffee Shops",  # RHYTHM ZERO
        "320252410422419622": "Rides & Taxis",  # UBER
        # 2025-08-27
        "320252390364412089": "Delivery & Takeout",  # DOORDASH
        "320252400387656798": "Groceries",  # DELI POINT
        "320252390362183678": "Coffee Shops",  # RHYTHM ZERO
        "320252390359502072": "Coffee Shops",  # SP COFFEE CHECK
        "320252390365034344": "Meal Kits",  # HELLOFRESH
        # 2025-08-26
        "320252380335155321": "Electronics & Gadgets",  # AMAZON MARKETPLACE
        "320252380335652559": "Clothing & Accessories",  # ATELIER COUTURE
        "320252390381633208": "Groceries",  # DELI POINT
        "320252380334521269": "Restaurants",  # KIJITORA
        "320252380332114373": "Coffee Shops",  # SP COFFEE CHECK
        "320252390377780175": "Restaurants",  # LITTLE TIFFIN
        "320252380340680907": "Home Services & Maintenance",  # ORKIN
        # 2025-08-25
        "320252370304758234": "Electronics & Gadgets",  # AMAZON MARKETPLACE
        "320252370308699143": "Electronics & Gadgets",  # AMAZON MARKETPLACE
        "320252390376068518": "Groceries",  # JUBILEE MARKET PLACE
        "320252370314017171": "Coffee Shops",  # RHYTHM ZERO
        "320252370304975698": "Coffee Shops",  # SP COFFEE CHECK
        "320252370325398773": "Clothing & Accessories",  # ETSY
        "320252370305538831": "Furniture & Appliances",  # LULU AND GEORGIA
        # 2025-08-24
        "320252370318628124": "Electronics & Gadgets",  # AMAZON MARKETPLACE
        "320252370318495582": "Electronics & Gadgets",  # AMAZON.COM
    }

    # -------------------------
    # Assert rows persisted with expected categories (idempotent upsert semantics)
    # -------------------------
    with session_scope(database_url=db_url) as session:
        rows = session.query(FaTransaction.external_id, FaTransaction.category).all()
        got = {eid: cat for (eid, cat) in rows}

    # Sanity: make sure we actually wrote the same number of rows
    assert len(got) == len(expected)
    # Exact match on category assignments
    assert got == expected
