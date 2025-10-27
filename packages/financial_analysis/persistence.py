# ruff: noqa: I001
"""Persistence integration for financial_analysis.

Functions here write transactions and category updates to the shared database
owned by ``libs/db``. They rely on SQLAlchemy ORM models defined in
``db.models.finance`` and a session provided by ``db.client``.

Scope:
- Upsert transactions into ``fa_transactions`` (raw JSONB + canonical columns).
- Update category fields for categorized transactions.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from db.models.finance import FaTransaction
from .models import CategorizedTransaction


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

    _d = _to_date(tx.get("date"))
    payload = {
        "provider": (source_provider or "").strip().lower(),
        "id": _norm_str(tx.get("id")),
        "amount": None,
        "date": _d.isoformat() if _d else None,
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

    payloads_with_eid: list[dict[str, Any]] = []
    payloads_without_eid: list[dict[str, Any]] = []

    for tx in transactions:
        external_id = _norm_str(tx.get("id"))
        amount_d = _to_decimal_2(tx.get("amount"))
        date_d = _to_date(tx.get("date"))
        description = _norm_str(tx.get("description"))
        merchant = _norm_str(tx.get("merchant"))
        memo = _norm_str(tx.get("memo"))
        fingerprint = compute_fingerprint(source_provider=source_provider, tx=tx)
        # Prefer merchant for a first-pass display label; fallback to description
        display_name = merchant or description

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
            "display_name": display_name,
            "updated_at": now,
        }
        # Only mark source="import" when we actually have a non-empty display name;
        # otherwise allow the DB default ("unknown") to stand for clearer semantics.
        if display_name:
            insert_values["display_name_source"] = "import"
        if external_id is not None:
            payloads_with_eid.append(insert_values)
        else:
            payloads_without_eid.append(insert_values)

    if payloads_with_eid:
        stmt = pg_insert(FaTransaction).values(payloads_with_eid)
        stmt = stmt.on_conflict_do_update(
            index_elements=[FaTransaction.source_provider, FaTransaction.external_id],
            index_where=FaTransaction.external_id.isnot(None),
            set_={
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
        session.execute(stmt)

    if payloads_without_eid:
        stmt = pg_insert(FaTransaction).values(payloads_without_eid)
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
    only_unverified: bool = False,
    use_item_confidence: bool = False,
) -> None:
    """Update category fields on matching rows in ``fa_transactions``.

    Matching strategy mirrors :func:`upsert_transactions`.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    source_provider:
        Provider key used to scope matches (e.g., "amex", "chase").
    categorized:
        Iterable of categorized transactions to apply.
    category_source:
        Label recorded in the DB for this update (e.g., "llm", "manual").
    category_confidence:
        When provided and ``use_item_confidence`` is False, this value is
        applied to all rows. When ``use_item_confidence`` is True, this value
        is ignored and each row derives confidence from
        ``item.revised_score`` when present, else ``item.score``.
    only_unverified:
        When True, apply updates only to rows where ``verified`` is False to
        avoid clobbering operator-reviewed categories.
    use_item_confidence:
        When True, store per-row confidence as described above.
    """

    now = func.now()

    for item in categorized:
        tx = item.transaction
        category = item.category
        external_id = _norm_str(tx.get("id"))
        # Choose confidence per update
        effective_confidence: float | None
        if use_item_confidence:
            effective_confidence = (
                item.revised_score if item.revised_score is not None else item.score
            )
        else:
            effective_confidence = category_confidence

        if external_id is not None:
            stmt = (
                update(FaTransaction)
                .where(
                    (FaTransaction.source_provider == source_provider)
                    & (FaTransaction.external_id == external_id)
                )
            )
            if only_unverified:
                stmt = stmt.where(FaTransaction.verified.is_(False))
            stmt = stmt.values(
                category=category,
                category_source=category_source,
                category_confidence=effective_confidence,
                categorized_at=now,
                updated_at=now,
            )
            session.execute(stmt)
        else:
            fingerprint = compute_fingerprint(source_provider=source_provider, tx=tx)
            stmt = update(FaTransaction).where(
                FaTransaction.fingerprint_sha256 == fingerprint
            )
            if only_unverified:
                stmt = stmt.where(FaTransaction.verified.is_(False))
            stmt = stmt.values(
                category=category,
                category_source=category_source,
                category_confidence=effective_confidence,
                categorized_at=now,
                updated_at=now,
            )
            session.execute(stmt)

def auto_persist_high_confidence(
    session: Session,
    *,
    source_provider: str,
    source_account: str | None,
    suggestions: Iterable[CategorizedTransaction],
    min_confidence: float = 0.7,
) -> int:
    """Persist high-confidence suggestions to the DB.

    Upserts the involved transactions and applies category updates for suggestions
    whose effective confidence (``revised_score`` when present, else ``score``)
    exceeds ``min_confidence``. Updates only rows where ``verified`` is False and
    stores per-row confidence from the item.
    """

    def _effective_score(it: CategorizedTransaction) -> float | None:
        return it.revised_score if it.revised_score is not None else it.score

    hi_conf: list[CategorizedTransaction] = [
        it for it in suggestions if (_effective_score(it) or 0.0) > min_confidence
    ]
    if not hi_conf:
        return 0

    upsert_transactions(
        session,
        source_provider=source_provider,
        source_account=source_account,
        transactions=[it.transaction for it in hi_conf],
    )
    apply_category_updates(
        session,
        source_provider=source_provider,
        categorized=hi_conf,
        category_source="llm",
        category_confidence=None,
        only_unverified=True,
        use_item_confidence=True,
    )
    return len(hi_conf)


__all__ = [
    "compute_fingerprint",
    "upsert_transactions",
    "apply_category_updates",
    "auto_persist_high_confidence",
]
