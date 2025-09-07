# ruff: noqa: I001
"""Persistence integration for financial_analysis.

Functions here write transactions and category updates to the shared database
owned by ``libs/db``. They rely on SQLAlchemy ORM models defined in
``db.models.finance`` and a session provided by ``db.client``.

Scope:
- Upsert transactions into ``fa_transactions`` (raw JSONB + canonical columns).
- Update category fields for categorized transactions.
- Provide a stub to persist refund pairs for future use.
"""

from __future__ import annotations  # ruff: noqa: I001

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from db.models.finance import FaTransaction
from .models import CategorizedTransaction, RefundMatch


def _to_decimal_2(raw: Any) -> Decimal | None:
    if raw is None:
        return None
    try:
        d = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _to_date(raw: Any) -> date | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        # Expect YYYY-MM-DD
        parts = [int(p) for p in s.split("-")]
        if len(parts) != 3:
            return None
        return date(parts[0], parts[1], parts[2])
    except Exception:
        return None


def _norm_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def compute_fingerprint(
    *,
    source_provider: str,
    tx: Mapping[str, Any],
) -> str:
    """Compute a stable SHA-256 fingerprint over canonical fields.

    Fields used: provider (lowercased), id (or None), amount (2dp string), date (YYYY-MM-DD),
    merchant (trimmed), description (trimmed).
    """

    payload = {
        "provider": (source_provider or "").strip().lower(),
        "id": _norm_str(tx.get("id")),
        "amount": None,
        "date": _norm_str(tx.get("date")),
        "merchant": _norm_str(tx.get("merchant")),
        "description": _norm_str(tx.get("description")),
    }
    amt = _to_decimal_2(tx.get("amount"))
    if amt is not None:
        payload["amount"] = f"{amt:.2f}"

    # Ensure deterministic JSON serialization
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def upsert_transactions(
    session: Session,
    *,
    source_provider: str,
    transactions: Iterable[Mapping[str, Any]],
    source_account: str | None = None,
) -> None:
    """Insert or update transactions into ``fa_transactions``.

    Idempotency rules:
    - If ``external_id`` (CTV ``id``) is present, upsert on
      ``(source_provider, external_id)`` (partial unique index target).
    - Otherwise, upsert on ``fingerprint_sha256``.
    """

    now = func.now()

    for tx in transactions:
        external_id = _norm_str(tx.get("id"))
        amount_d = _to_decimal_2(tx.get("amount"))
        date_d = _to_date(tx.get("date"))
        description = _norm_str(tx.get("description"))
        merchant = _norm_str(tx.get("merchant"))
        memo = _norm_str(tx.get("memo"))
        fingerprint = compute_fingerprint(source_provider=source_provider, tx=tx)

        insert_values = {
            "source_provider": source_provider,
            "source_account": source_account,
            "external_id": external_id,
            "fingerprint_sha256": fingerprint,
            "raw_record": dict(tx),
            "currency_code": "USD",
            "amount": amount_d,
            "date": date_d,
            "description": description,
            "merchant": merchant,
            "memo": memo,
            "updated_at": now,
        }

        stmt = pg_insert(FaTransaction).values(**insert_values)

        if external_id is not None:
            # Upsert on natural key when external_id is present (partial unique index)
            stmt = stmt.on_conflict_do_update(
                index_elements=[FaTransaction.source_provider, FaTransaction.external_id],
                index_where=FaTransaction.external_id.isnot(None),
                set_={
                    # Preserve category fields; update canonical columns and raw JSON only
                    "raw_record": stmt.excluded.raw_record,
                    "currency_code": stmt.excluded.currency_code,
                    "amount": stmt.excluded.amount,
                    "date": stmt.excluded.date,
                    "description": stmt.excluded.description,
                    "merchant": stmt.excluded.merchant,
                    "memo": stmt.excluded.memo,
                    "fingerprint_sha256": stmt.excluded.fingerprint_sha256,
                    "updated_at": now,
                },
            )
        else:
            # Upsert on fingerprint fallback when no external id exists
            stmt = stmt.on_conflict_do_update(
                index_elements=[FaTransaction.fingerprint_sha256],
                set_={
                    "raw_record": stmt.excluded.raw_record,
                    "currency_code": stmt.excluded.currency_code,
                    "amount": stmt.excluded.amount,
                    "date": stmt.excluded.date,
                    "description": stmt.excluded.description,
                    "merchant": stmt.excluded.merchant,
                    "memo": stmt.excluded.memo,
                    "updated_at": now,
                },
            )

        session.execute(stmt)


def apply_category_updates(
    session: Session,
    *,
    source_provider: str,
    categorized: Iterable[CategorizedTransaction],
    category_source: str = "llm",
    category_confidence: float | None = None,
) -> None:
    """Update category fields on matching rows in ``fa_transactions``.

    Matching strategy mirrors :func:`upsert_transactions`.
    """

    now = datetime.utcnow()

    for item in categorized:
        tx = item.transaction
        category = item.category
        external_id = _norm_str(tx.get("id"))

        if external_id is not None:
            stmt = (
                update(FaTransaction)
                .where(
                    (FaTransaction.source_provider == source_provider)
                    & (FaTransaction.external_id == external_id)
                )
                .values(
                    category=category,
                    category_source=category_source,
                    category_confidence=category_confidence,
                    categorized_at=now,
                )
            )
            session.execute(stmt)
        else:
            fingerprint = compute_fingerprint(source_provider=source_provider, tx=tx)
            stmt = (
                update(FaTransaction)
                .where(FaTransaction.fingerprint_sha256 == fingerprint)
                .values(
                    category=category,
                    category_source=category_source,
                    category_confidence=category_confidence,
                    categorized_at=now,
                )
            )
            session.execute(stmt)


def persist_refund_pairs(
    session: Session, *, pairs: Iterable[RefundMatch]
) -> None:  # pragma: no cover - not wired yet
    """Persist refund links into ``fa_refund_pairs`` (stub).

    This function will be invoked by future ``identify_refunds`` integration.
    It assumes both sides of the pair already exist in ``fa_transactions`` and
    will insert unique pairs by (expense_id, refund_id).
    """

    # This is intentionally left as a minimal stub. Implementers should look up
    # the transaction IDs (by external_id or fingerprint) and insert via a
    # unique-on pair upsert.
    return None


__all__ = [
    "compute_fingerprint",
    "upsert_transactions",
    "apply_category_updates",
    "persist_refund_pairs",
]
