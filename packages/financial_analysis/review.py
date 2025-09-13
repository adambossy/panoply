"""Interactive review workflow for transaction categories.

This module holds the concrete implementation of
``review_transaction_categories`` plus its supporting helpers. The top‑level
function is intentionally concise and delegates to small, testable helpers for
preparation, grouping, querying, prompting, and persistence.
"""

from __future__ import annotations

import builtins
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from db.client import session_scope
from db.models.finance import FaCategory, FaTransaction
from sqlalchemy import func, select, update

from .models import CategorizedTransaction
from .persistence import compute_fingerprint, upsert_transactions


@dataclass(frozen=True, slots=True)
class _PreparedItem:
    """Prepared view of an input row with identifiers for grouping/DB lookups."""

    pos: int
    tx: Mapping[str, Any]
    suggested: str
    external_id: str | None
    fingerprint: str


def _norm_id(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _materialize_and_prepare(
    transactions_with_categories: Iterable[CategorizedTransaction], *, source_provider: str
) -> tuple[list[CategorizedTransaction], list[_PreparedItem]]:
    items: list[CategorizedTransaction] = list(transactions_with_categories)
    prepared: list[_PreparedItem] = []
    for idx, ci in enumerate(items):
        tx = ci.transaction
        eid = _norm_id(tx.get("id"))
        fp = compute_fingerprint(source_provider=source_provider, tx=tx)
        prepared.append(
            _PreparedItem(
                pos=idx,
                tx=tx,
                suggested=ci.category,
                external_id=eid,
                fingerprint=fp,
            )
        )
    return items, prepared




class _DisjointSet:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, a: int) -> int:
        parent = self.parent
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _build_groups(prepared: list[_PreparedItem]) -> dict[int, list[int]]:
    """Build connectivity groups over indices by external_id OR fingerprint."""

    n = len(prepared)
    dsu = _DisjointSet(n)

    by_eid: defaultdict[str, list[int]] = defaultdict(list)
    by_fp: defaultdict[str, list[int]] = defaultdict(list)
    for i, prep in enumerate(prepared):
        if prep.external_id is not None:
            by_eid[prep.external_id].append(i)
        by_fp[prep.fingerprint].append(i)

    for _k, idxs in by_eid.items():
        base = idxs[0]
        for j in idxs[1:]:
            dsu.union(base, j)
    for _k, idxs in by_fp.items():
        base = idxs[0]
        for j in idxs[1:]:
            dsu.union(base, j)

    groups_map: defaultdict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups_map[dsu.find(i)].append(i)
    return groups_map




def _load_allowed_categories(session) -> set[str]:
    return {row[0] for row in session.execute(select(FaCategory.code)).all()}


def _query_group_duplicates(
    session,
    *,
    source_provider: str,
    source_account: str | None,
    group_eids: list[str],
    group_fps: list[str],
) -> list[tuple[str | None, Mapping[str, Any]]]:
    conds = []
    if group_eids:
        conds.append(FaTransaction.external_id.in_(group_eids))
    if group_fps:
        conds.append(FaTransaction.fingerprint_sha256.in_(group_fps))

    rows: list[tuple[str | None, Mapping[str, Any]]] = []
    if conds:
        stmt = (
            select(
                FaTransaction.category,
                FaTransaction.raw_record,
            )
            .where(FaTransaction.source_provider == source_provider)
            .where(FaTransaction.source_account == source_account)
            .where(conds[0] if len(conds) == 1 else (conds[0] | conds[1]))
        )
        rows = [(row[0], row[1]) for row in session.execute(stmt).all()]
    return rows


def _persist_group(
    session,
    *,
    source_provider: str,
    source_account: str | None,
    group_items: list[_PreparedItem],
    final_cat: str,
) -> None:
    # Ensure upsert before updates
    upsert_transactions(
        session,
        source_provider=source_provider,
        source_account=source_account,
        transactions=[it.tx for it in group_items],
    )

    now = func.now()
    eids = [p.external_id for p in group_items if p.external_id is not None]
    fps = [p.fingerprint for p in group_items if p.external_id is None]

    base = update(FaTransaction).where(FaTransaction.source_provider == source_provider)
    if source_account is None:
        base = base.where(FaTransaction.source_account.is_(None))
    else:
        base = base.where(FaTransaction.source_account == source_account)

    values = {
        "category": final_cat,
        "category_source": "manual",
        "category_confidence": None,
        "categorized_at": now,
        "verified": True,
        "updated_at": now,
    }

    if eids:
        session.execute(base.where(FaTransaction.external_id.in_(eids)).values(**values))
    if fps:
        session.execute(base.where(FaTransaction.fingerprint_sha256.in_(fps)).values(**values))




def _fmt_tx_row(tx: Mapping[str, Any]) -> str:
    raw_date = tx.get("date")
    d = (raw_date or "").strip() if isinstance(raw_date, str) else raw_date
    amt = tx.get("amount")
    desc = tx.get("description") or tx.get("merchant") or ""
    eid = tx.get("id")
    return f"{d or ''}\t{amt!s}\t{str(desc)[:60]}\t{eid or ''}"


def _print_rows_block(
    title: str, rows: list[str], *, exemplars: int, print_fn: Callable[..., None]
) -> None:
    print_fn(title)
    show = rows[:exemplars]
    for line in show:
        print_fn("  ", line)
    extra = len(rows) - len(show)
    if extra > 0:
        print_fn(f"  +{extra} more")


def _select_default_category(
    db_dupes: list[tuple[str | None, Mapping[str, Any]]], group_items: list[_PreparedItem]
) -> str | None:
    if db_dupes:
        cats = [cat for cat, _ in db_dupes if cat]
        if cats and len(set(cats)) == 1:
            return cats[0]
    # Fallback: most common suggestion
    counts = Counter(prep.suggested for prep in group_items)
    most_common = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    return most_common[0]

def review_transaction_categories(
    transactions_with_categories: Iterable[CategorizedTransaction],
    *,
    source_provider: str,
    source_account: str | None,
    database_url: str | None = None,
    exemplars: int = 5,
    input_fn: Callable[[str], str] = builtins.input,
    print_fn: Callable[..., None] = builtins.print,
) -> list[CategorizedTransaction]:
    """Interactive review-and-persist flow for transaction categories.

    Behavior
    --------
    - Group input transactions into duplicate groups where two items are in the
      same group if they share the same external id (``transaction['id']``) OR
      the same fingerprint (``compute_fingerprint``). Fingerprinting uses the
      provided ``source_provider`` as context.
    - For each group, query DB duplicates in ``fa_transactions`` matching the
      same ``(source_provider, source_account)`` and either any group external
      id or any group fingerprint.
    - Display a compact summary (first ``exemplars`` items, "+K more" for the
      remainder) for both the input group and any DB duplicates.
    - Prompt the operator to accept a default category (DB duplicates’
      unanimous category when present; otherwise the most‑common LLM suggestion
      in the group) or override with any valid ``fa_categories.code``.
    - On confirmation, persist the whole group: upsert all transactions, then
      set ``category=<chosen>``, ``category_source='manual'``,
      ``verified=true``, and timestamps (batched updates by identifier type);
      commit after each group.

    Parameters
    ----------
    input_fn:
        Function used to prompt for user input. Defaults to ``builtins.input``.
    print_fn:
        Function used to print output. Defaults to ``builtins.print``.

    Returns
    -------
    list[CategorizedTransaction]
        Finalized list reflecting the chosen category per input item.
    """

    # Materialize and precompute identifiers
    items, prepared = _materialize_and_prepare(
        transactions_with_categories, source_provider=source_provider
    )
    if not items:
        print_fn("No transactions to review.")
        return []

    groups_map = _build_groups(prepared)
    final: list[CategorizedTransaction] = list(items)

    with session_scope(database_url=database_url) as session:
        allowed = _load_allowed_categories(session)
        if not allowed:
            raise RuntimeError("No categories present in fa_categories; cannot proceed")

        # Deterministic order by first index in each group
        group_roots = sorted(groups_map.keys(), key=lambda r: min(groups_map[r]))

        for root in group_roots:
            idxs = groups_map[root]
            group_items = [prepared[i] for i in idxs]

            # Show input summary
            input_rows = [_fmt_tx_row(prep.tx) for prep in group_items]
            _print_rows_block(
                "Input group (date\tamount\tdesc/merchant\tid):",
                input_rows,
                exemplars=exemplars,
                print_fn=print_fn,
            )

            # Query duplicates for this group
            group_eids = [p.external_id for p in group_items if p.external_id is not None]
            group_fps = [p.fingerprint for p in group_items]
            db_dupes = _query_group_duplicates(
                session,
                source_provider=source_provider,
                source_account=source_account,
                group_eids=group_eids,
                group_fps=group_fps,
            )

            if db_dupes:
                dup_rows = [
                    _fmt_tx_row(rec) + (f"\t[{cat}]" if cat else "\t[uncategorized]")
                    for cat, rec in db_dupes
                ]
                _print_rows_block(
                    "DB duplicates (first matches shown):",
                    dup_rows,
                    exemplars=exemplars,
                    print_fn=print_fn,
                )
            else:
                print_fn("No DB duplicates matched for this group.")

            chosen_default = _select_default_category(db_dupes, group_items)
            print_fn(f"Proposed category: {chosen_default}")

            # Prompt until a valid category is provided
            while True:
                resp = input_fn(
                    "Press Enter to accept, or type a different category code: "
                ).strip()
                final_cat = chosen_default if not resp else resp
                assert final_cat is not None
                if final_cat in allowed:
                    break
                print_fn("Invalid category. Enter one of: " + ", ".join(sorted(allowed)))

            _persist_group(
                session,
                source_provider=source_provider,
                source_account=source_account,
                group_items=group_items,
                final_cat=final_cat,
            )

            # Update result list
            for prep in group_items:
                final[prep.pos] = CategorizedTransaction(
                    transaction=prep.tx, category=final_cat
                )

            session.commit()
            print_fn("Saved.")

    return final


__all__ = ["review_transaction_categories"]
