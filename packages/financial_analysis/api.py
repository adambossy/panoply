"""Public API interfaces and orchestration for the ``financial_analysis`` package.

This module primarily serves as a stable import surface. The concrete
implementation of :func:`categorize_expenses` now lives in
``financial_analysis.categorize`` and is re-exported here as a thin
compatibility shim. Other interfaces remain stubs and raise
``NotImplementedError`` by design.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

# Compatibility aliases and re-exports
from openai import OpenAI as OpenAI  # re-export for monkeypatch compatibility

from .categorize import categorize_expenses  # noqa: F401  (re-export)
from .models import (
    CategorizedTransaction,
    PartitionPeriod,
    RefundMatch,
    TransactionPartitions,
    Transactions,
)

# DB and persistence imports are intentionally local within functions to keep
# import-time costs low for consumers that don't use the DB-backed review flow.


def identify_refunds(transactions: Transactions) -> Iterable[RefundMatch]:
    """Identify expense/refund pairs by inverse amounts (interface only).

    Input
    -----
    transactions:
        A collection of :data:`~financial_analysis.models.TransactionRecord`
        items to search for refund relationships.

    Output
    ------
    An iterable of expense/refund pairs as
    :class:`~financial_analysis.models.RefundMatch`, where each element holds
    the full :data:`TransactionRecord` for the expense and its matching
    refund.

    Notes
    -----
    - The amount column name and format are unspecified (e.g., whether refunds
      are negative amounts, sign conventions, currency/rounding).
    - Date schema and any time-based disambiguation rules are not defined.
    """

    raise NotImplementedError


def partition_transactions(
    transactions: Transactions, partition_period: PartitionPeriod
) -> TransactionPartitions:
    """Partition a transaction collection into period-based subsets (interface only).

    Input
    -----
    transactions:
        A collection of transaction records.
    partition_period:
        A structured period spec (see
        :class:`~financial_analysis.models.PartitionPeriod`) that supports any
        combination of ``years``, ``months``, ``weeks``, and ``days``. Each
        field is optional and the fields are not mutually exclusive.

    Output
    ------
    An iterable of partitions, where each partition is a subset of the input
    transactions (see :data:`~financial_analysis.models.TransactionPartitions`).

    Notes
    -----
    - The required date column name and its format are not specified and must
      be clarified for any implementation.
    - The ordering of transactions within and across partitions is unspecified.
    """

    raise NotImplementedError


def report_trends(transactions: Transactions) -> str:
    """Produce a pretty-printed trends table by category by month (interface only).

    Input
    -----
    transactions:
        A collection of transaction records.

    Output
    ------
    A string containing a pretty-printed table showing spending totals by
    category by month and overall totals. Rendering/printing of this string is
    the caller's responsibility; this API returns the string only.

    Notes
    -----
    - Required column names and formats (e.g., date, amount, category) are not
      specified and require clarification.
    - Timezone/calendar assumptions and how months are defined (posting vs
      transaction date) are unspecified.
    - Category normalization rules and aggregation semantics are not defined.
    """

    raise NotImplementedError


def review_transaction_categories(
    transactions_with_categories: Iterable[CategorizedTransaction],
    *,
    source_provider: str,
    source_account: str | None,
    database_url: str | None = None,
    exemplars: int = 5,
) -> list[CategorizedTransaction]:
    """Interactive review-and-persist flow for transaction categories.

    Behavior (Issue #14 + clarifications, Sept 13, 2025):
    - Group input transactions into duplicate groups where two items are in the
      same group if they share the same external_id (``transaction['id']``) OR
      the same fingerprint (``compute_fingerprint``). Fingerprinting uses the
      provided ``source_provider`` as context.
    - For each group, query DB duplicates in ``fa_transactions`` matching
      (source_provider, source_account) AND either any group external_id or any
      group fingerprint.
    - Display a compact summary (first ``exemplars`` items, "+K more" for the
      remainder) for both the input group and any DB duplicates.
    - Prompt the user to accept a default category (DB duplicates' unanimous
      category when present; otherwise the most common LLM suggestion in the
      group) or to override with a different valid category code.
    - On confirmation, persist all transactions in the group: upsert rows,
      then set ``category=<chosen>`, ``category_source='manual'``, and
      ``verified=true``.

    Returns the finalized list of :class:`CategorizedTransaction` reflecting
    the chosen category per input item.
    """

    from db.client import session_scope
    from db.models.finance import FaCategory, FaTransaction
    from sqlalchemy import func, select, update

    from .persistence import compute_fingerprint, upsert_transactions

    # Materialize inputs (preserve order)
    items: list[CategorizedTransaction] = list(transactions_with_categories)
    if not items:
        print("No transactions to review.")
        return []

    # Pre-compute identifiers used for grouping and DB lookups
    @dataclass(frozen=True, slots=True)
    class _Item:
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

    prepared: list[_Item] = []
    for idx, ci in enumerate(items):
        tx = ci.transaction
        eid = _norm_id(tx.get("id"))
        fp = compute_fingerprint(source_provider=source_provider, tx=tx)
        prepared.append(
            _Item(
                pos=idx,
                tx=tx,
                suggested=ci.category,
                external_id=eid,
                fingerprint=fp,
            )
        )

    # Build groups using connectivity over external_id OR fingerprint.
    # Union-Find (Disjoint Set Union) across positions 0..n-1.
    n = len(prepared)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    by_eid: defaultdict[str, list[int]] = defaultdict(list)
    by_fp: defaultdict[str, list[int]] = defaultdict(list)
    for i, prep in enumerate(prepared):
        if prep.external_id is not None:
            by_eid[prep.external_id].append(i)
        by_fp[prep.fingerprint].append(i)

    for _k, idxs in by_eid.items():
        base = idxs[0]
        for j in idxs[1:]:
            union(base, j)
    for _k, idxs in by_fp.items():
        base = idxs[0]
        for j in idxs[1:]:
            union(base, j)

    groups_map: defaultdict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups_map[find(i)].append(i)

    # Open a session for the review loop. Keep the session alive across groups
    # for category list caching; issue short transactions per group via
    # session_scope semantics.
    final: list[CategorizedTransaction] = list(items)  # will rewrite .category per choice

    with session_scope(database_url=database_url) as session:
        # Load allowed categories from DB to validate input.
        allowed: set[str] = {
            row[0] for row in session.execute(select(FaCategory.code)).all()
        }
        if not allowed:
            raise RuntimeError("No categories present in fa_categories; cannot proceed")

        # Process groups in deterministic order by the smallest original index
        # within each group.
        group_roots = sorted(groups_map.keys(), key=lambda r: min(groups_map[r]))

        def _fmt_tx(tx: Mapping[str, Any]) -> str:
            raw_date = tx.get("date")
            d = (raw_date or "").strip() if isinstance(raw_date, str) else raw_date
            amt = tx.get("amount")
            desc = tx.get("description") or tx.get("merchant") or ""
            eid = tx.get("id")
            return f"{d or ''}\t{amt!s}\t{str(desc)[:60]}\t{eid or ''}"

        def _print_list(title: str, rows: list[str]) -> None:
            print(title)
            show = rows[:exemplars]
            for line in show:
                print("  ", line)
            extra = len(rows) - len(show)
            if extra > 0:
                print(f"  +{extra} more")

        for root in group_roots:
            idxs = groups_map[root]
            group_items = [prepared[i] for i in idxs]

            # Display input group summary
            input_rows = [_fmt_tx(prep.tx) for prep in group_items]
            _print_list("Input group (date\tamount\tdesc/merchant\tid):", input_rows)

            # Collect group identifiers for DB query
            group_eids = [prep.external_id for prep in group_items if prep.external_id is not None]
            group_fps = [prep.fingerprint for prep in group_items]

            # Query duplicates in DB for this group
            conds = []
            if group_eids:
                conds.append(FaTransaction.external_id.in_(group_eids))
            if group_fps:
                conds.append(FaTransaction.fingerprint_sha256.in_(group_fps))

            db_dupes: list[tuple[str | None, Mapping[str, Any]]]
            db_dupes = []
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
                db_dupes = [(row[0], row[1]) for row in session.execute(stmt).all()]

            # Show DB duplicates if present
            chosen_default: str | None = None
            if db_dupes:
                dup_rows = [
                    _fmt_tx(rec) + (f"\t[{cat}]" if cat else "\t[uncategorized]")
                    for cat, rec in db_dupes
                ]
                _print_list("DB duplicates (first matches shown):", dup_rows)
                cats = [cat for cat, _ in db_dupes if cat]
                if cats and len(set(cats)) == 1:
                    chosen_default = cats[0]
            else:
                print("No DB duplicates matched for this group.")

            # Determine fallback default from suggestions when DB did not force one
            if not chosen_default:
                counts = Counter(prep.suggested for prep in group_items)
                # Most common suggestion (ties resolved by lexical order for stability)
                most_common = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
                chosen_default = most_common[0]

            # Prompt user: accept default or enter a different code
            print(f"Proposed category: {chosen_default}")
            while True:
                resp = input(
                    "Press Enter to accept, or type a different category code: "
                ).strip()
                if not resp:
                    final_cat = chosen_default
                else:
                    final_cat = resp
                assert final_cat is not None
                if final_cat in allowed:
                    break
                print(
                    "Invalid category. Enter one of: " + ", ".join(sorted(allowed))
                )

            # Persist: ensure rows exist, then set category + manual + verified
            upsert_transactions(
                session,
                source_provider=source_provider,
                source_account=source_account,
                transactions=[it.tx for it in group_items],
            )

            now = func.now()
            # Batch updates by identifier type for efficiency and to avoid
            # cross-provider/account updates.
            eids = [p.external_id for p in group_items if p.external_id is not None]
            fps = [p.fingerprint for p in group_items if p.external_id is None]

            base = update(FaTransaction).where(
                FaTransaction.source_provider == source_provider
            )
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
                session.execute(
                    base.where(FaTransaction.external_id.in_(eids)).values(**values)
                )
            if fps:
                session.execute(
                    base.where(FaTransaction.fingerprint_sha256.in_(fps)).values(**values)
                )

            # Update result objects to reflect the final choice
            for prep in group_items:
                final[prep.pos] = CategorizedTransaction(transaction=prep.tx, category=final_cat)

            # Make each group durable independently.
            session.commit()
            print("Saved.")

    return final
