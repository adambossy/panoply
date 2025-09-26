"""Interactive review workflow for transaction categories.

This module holds the concrete implementation of
``review_transaction_categories`` plus its supporting helpers. The top‑level
function is intentionally concise and delegates to small, testable helpers for
preparation, grouping, querying, prompting, and persistence.
"""

from __future__ import annotations

import builtins
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from db.client import session_scope
from db.models.finance import FaCategory, FaTransaction
from sqlalchemy import distinct, func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError

from .categories import createCategory, list_top_level_categories
from .models import CategorizedTransaction
from .persistence import compute_fingerprint, upsert_transactions
from .term_ui import (
    TOP_LEVEL_SENTINEL,
    CreateCategoryRequest,
    prompt_new_category_name,
    prompt_select_parent,
)
from .term_ui import (
    select_category_or_create as _select_category_or_create,
)

# ----------------------------------------------------------------------------
# Preparation and grouping
# ----------------------------------------------------------------------------


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


def _norm_merchant_key(tx: Mapping[str, Any]) -> str | None:
    """Return a case/whitespace‑insensitive key for grouping by merchant.

    Falls back to ``description`` when ``merchant`` is missing/empty. Collapses
    internal whitespace to a single space and lower‑cases the result. Returns
    ``None`` when neither field is present.
    """
    raw = tx.get("merchant") or tx.get("description")
    if raw is None:
        return None
    s = unicodedata.normalize("NFKC", str(raw)).strip()
    if not s:
        return None
    # Collapse internal whitespace (including newlines/tabs) and case‑fold
    return " ".join(s.split()).casefold()


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
    """Group indices by normalized merchant/description; no legacy fallback.

    New behavior (per issue #44):
    - Items sharing the same normalized merchant (or, when merchant is empty,
      the same normalized description) are grouped together, regardless of
      differing ids, amounts, or dates.
    - When both merchant and description are empty, each item forms its own
      singleton group (we do not merge by external id or fingerprint).
    """

    # Primary: group by normalized merchant/description key
    by_merch: defaultdict[str, list[int]] = defaultdict(list)
    # Track items without a merchant/description key; they become singletons
    fallback_idxs: list[int] = []

    for i, prep in enumerate(prepared):
        key = _norm_merchant_key(prep.tx)
        if key is None:
            fallback_idxs.append(i)
        else:
            by_merch[key].append(i)

    # Start with merchant-based groups, assigning deterministic roots
    groups_map: dict[int, list[int]] = {}
    for idxs in by_merch.values():
        root = min(idxs)
        groups_map[root] = sorted(idxs)

    # Items without a key: emit as singletons with deterministic roots
    for i in fallback_idxs:
        groups_map[i] = [i]

    return groups_map


# ----------------------------------------------------------------------------
# DB queries and persistence
# ----------------------------------------------------------------------------


def _load_allowed_categories(session) -> set[str]:
    # Use scalars() for clarity and to avoid tuple indexing
    return set(session.scalars(select(FaCategory.code)).all())


def _query_group_duplicates(
    session,
    *,
    source_provider: str,
    source_account: str | None,
    group_eids: list[str],
    group_fps: list[str],
    exemplars: int,
) -> tuple[list[tuple[str | None, Mapping[str, Any]]], str | None]:
    """Return a limited sample of duplicates and a unanimous default category.

    Optimizes IO by splitting the work into:
    - an aggregate over matches to determine if all non-null categories agree;
    - a limited sample (``exemplars``) of rows for display.
    """
    conds = []
    if group_eids:
        conds.append(FaTransaction.external_id.in_(group_eids))
    if group_fps:
        conds.append(FaTransaction.fingerprint_sha256.in_(group_fps))

    rows: list[tuple[str | None, Mapping[str, Any]]] = []
    unanimous: str | None = None
    if conds:
        base_filters = (
            (FaTransaction.source_provider == source_provider),
            (FaTransaction.source_account == source_account),
            or_(*conds),
        )

        # Aggregate: count distinct non-null categories among matches
        agg_stmt = (
            select(func.count(distinct(FaTransaction.category)))
            .where(*base_filters)
            .where(FaTransaction.category.is_not(None))
        )
        distinct_count = session.execute(agg_stmt).scalar_one()
        if distinct_count == 1:
            # Fetch the single category value
            unanimous = session.execute(
                select(FaTransaction.category)
                .where(*base_filters)
                .where(FaTransaction.category.is_not(None))
                .limit(1)
            ).scalar_one()

        # Fetch a limited sample for display
        rows_stmt = (
            select(FaTransaction.category, FaTransaction.raw_record)
            .where(*base_filters)
            .limit(exemplars)
        )
        rows = [(row[0], row[1]) for row in session.execute(rows_stmt).all()]

    return rows, unanimous


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
    # Use all fingerprints from the group; do not exclude those that also have an external_id
    fps = [p.fingerprint for p in group_items]

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

    # Apply a single OR condition across the union of identifiers within the provider/account scope
    conds = []
    if eids:
        conds.append(FaTransaction.external_id.in_(eids))
    if fps:
        conds.append(FaTransaction.fingerprint_sha256.in_(fps))
    if conds:
        session.execute(base.where(or_(*conds)).values(**values))


# ----------------------------------------------------------------------------
# Presentation helpers
# ----------------------------------------------------------------------------


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
        # Emit a single formatted string per line to avoid separator artifacts
        print_fn(f"  {line}")
    extra = len(rows) - len(show)
    if extra > 0:
        print_fn(f"  +{extra} more")


def _fmt_amount(value: Any) -> str:
    try:
        v = float(str(value).replace(",", "").strip())
    except Exception:  # pragma: no cover - defensive
        return f"${value}"
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


def _normalize_amount_str(value: Any) -> str:
    """Normalize an amount to a simple numeric string with an optional leading '-'.

    - Strips commas and a leading '$' if present.
    - Converts accounting parentheses into a leading '-'.
    - Preserves a single leading '-' if present after normalization.
    """
    s = str(value).strip()
    s = s.replace(",", "")
    if s.startswith("$"):
        s = s[1:].strip()
    if s.startswith("(") and s.endswith(")") and len(s) >= 2:
        inner = s[1:-1].strip()
        if inner.startswith("$"):
            inner = inner[1:].strip()
        s = f"-{inner}"
    return s


def _is_negative_amount(value: Any) -> bool:
    """Best-effort negativity check that tolerates strings and accounting style."""
    s = _normalize_amount_str(value)
    return s.startswith("-")


def _fmt_abs_amount(value: Any) -> str:
    """Format an amount without its sign for headline readability."""
    s = _normalize_amount_str(value)
    try:
        v = float(s)
        return f"${abs(v):,.2f}"
    except Exception:  # pragma: no cover - defensive
        # Ensure no double '$' and drop any leading '-'
        return f"${s.lstrip('-').lstrip('$')}"


def _intent_from_amount(value: Any) -> tuple[str, str]:
    """Map amount sign to intent (verb, preposition).

    Assumes normalized sign semantics: negative = spend/outflow, non-negative =
    income/inflow. If different connectors use different conventions, that
    should be normalized during ingestion so presentation stays consistent.
    """
    neg = _is_negative_amount(value)
    return ("spent", "at") if neg else ("received", "from")


def _fmt_tx_summary(tx: Mapping[str, Any]) -> tuple[str, str]:
    """Return (headline, id_line) for a concise one-transaction summary."""
    amount_raw = tx.get("amount")
    amount = _fmt_abs_amount(amount_raw)
    verb, prep = _intent_from_amount(amount_raw)

    name_raw = tx.get("merchant") or tx.get("description") or ""
    name = str(name_raw).strip() or "unknown merchant"

    date_raw = tx.get("date")
    date = (str(date_raw).strip() if date_raw is not None else "").strip() or "unknown date"

    eid = str(tx.get("id") or "unknown")

    headline = f"{amount} {verb} {prep} `{name}` on {date}"
    id_line = f"ID = {eid}."
    return headline, id_line


def _render_group_context(
    *,
    group_items: list[_PreparedItem],
    db_dupes: list[tuple[str | None, Mapping[str, Any]]],
    exemplars: int,
    print_fn: Callable[..., None],
) -> None:
    """Render the input group and any DB duplicate examples using a friendly style."""

    # Friendly, human-readable summaries. When the group is a single item,
    # inline the "no duplicates" message on the ID line to match the desired UX.
    if len(group_items) == 1:
        tx = group_items[0].tx
        headline, id_line = _fmt_tx_summary(tx)
        print_fn(headline)
        if db_dupes:
            print_fn(id_line)
            _print_rows_block(
                "DB duplicates (first matches shown):",
                _format_dup_rows(db_dupes),
                exemplars=exemplars,
                print_fn=print_fn,
            )
        else:
            print_fn(id_line + " No DB duplicates matched.")
        print_fn("")  # blank line after the group block
        return

    # Multi-item group: list each item compactly, then show group-level dup info
    for prep in group_items[:exemplars]:
        headline, id_line = _fmt_tx_summary(prep.tx)
        print_fn(headline)
        print_fn(id_line)
    extra = len(group_items) - min(len(group_items), exemplars)
    if extra > 0:
        print_fn(f"+{extra} more in this group")

    if db_dupes:
        _print_rows_block(
            "DB duplicates (first matches shown):",
            _format_dup_rows(db_dupes),
            exemplars=exemplars,
            print_fn=print_fn,
        )
    else:
        print_fn("No DB duplicates matched for this group.")
    print_fn("")


def _format_dup_rows(db_dupes: list[tuple[str | None, Mapping[str, Any]]]) -> list[str]:
    """Format duplicate sample rows once to avoid repetition at call sites."""
    return [
        _fmt_tx_row(rec) + (f"\t[{cat}]" if cat else "\t[uncategorized]") for cat, rec in db_dupes
    ]


# ----------------------------------------------------------------------------
# Category proposal and selection
# ----------------------------------------------------------------------------


def _select_default_category(
    *,
    db_unanimous: str | None,
    group_items: list[_PreparedItem],
) -> str:
    """Choose the default category for a group.

    Prefers the unanimously agreed non-null category from DB duplicates when
    present; otherwise falls back to the most-common suggestion among the input
    group. Always returns a category string for non-empty groups.
    """
    if db_unanimous:
        return db_unanimous
    counts = Counter(prep.suggested for prep in group_items)
    most_common = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    return most_common[0]


def _prepare_selector_inputs(
    *,
    allowed: set[str],
    default_category: str,
) -> tuple[list[str], str]:
    """Return a deterministic options list and the default value for the selector.

    This isolates normalization, sorting, and de‑duplication concerns from the
    selection logic. The returned list is safe to pass to the terminal UI.
    """
    options = sorted(allowed)  # stable, case‑sensitive sort preserves current UX
    return options, default_category


def _is_creation_enabled(allow_create: bool | None) -> bool:
    """Resolve the effective creation toggle.

    Creation is enabled by default (None -> True) and can be explicitly
    disabled by passing ``False``. Session permissions, if any, are enforced
    upstream; this helper preserves current behavior.
    """
    return True if allow_create is None else bool(allow_create)


def _invoke_category_selector(
    *,
    selector: Callable[[Iterable[str], str], str] | None,
    allowed_options: list[str],
    default_category: str,
    allow_create: bool,
) -> str | CreateCategoryRequest:
    """Invoke either the injected selector or the creation‑aware UI.

    Ensures type safety for the injected path before performing string ops.
    """
    if selector is not None:
        resp = selector(allowed_options, default_category)
        if not isinstance(resp, str):
            raise TypeError(f"selector must return a string; got {type(resp).__name__}")
        return resp.strip()
    # Interactive, creation‑aware UI path
    return _select_category_or_create(
        allowed_options,
        default=default_category,
        allow_create=allow_create,
    )


def _process_create_category_intent(
    *,
    session,
    intent: CreateCategoryRequest,
    chosen_default: str,
    allowed: set[str],
    input_fn: Callable[[str], str],
    print_fn: Callable[..., None],
) -> str | None:
    """Handle a creation intent: prompt, persist, feedback, and return selection.

    Returns the selected category code on success. Returns ``None`` when the
    operator cancels and the caller should reopen the selector.
    """
    # Open the mini‑prompt to collect/confirm the name, preserving the prior
    # suggestion as the initial value.
    initial_name = (intent.name or chosen_default).strip()
    while True:
        name = prompt_new_category_name(initial=initial_name)
        if name is None:
            # Cancel/back: return to selector, keep prior default.
            return None
        # Prompt for parent selection (top-level allowed)
        parents = list_top_level_categories(session)
        parent_names = [p["display_name"] for p in parents]
        parent_choice = prompt_select_parent(parent_names)
        if parent_choice is None:
            # Cancel: reopen selector
            return None
        parent_code: str | None
        if parent_choice == TOP_LEVEL_SENTINEL:
            parent_code = None
        else:
            # Lookup chosen parent by display_name (case-insensitive)
            parent_lookup = {p["display_name"].lower(): p["code"] for p in parents}
            parent_code = parent_lookup.get(parent_choice.lower())
            if parent_code is None:
                # Shouldn't happen; defensive fallback to top-level
                parent_code = None
        try:
            with session.begin_nested():
                res = createCategory(session, code=name, parent_code=parent_code)
        except ValueError as e:  # validation/user error; allow retry without exiting
            print_fn(str(e))
            # Let the operator try another name/parent
            continue
        except SQLAlchemyError as e:  # transient DB/network errors
            print_fn(f"Error creating category: {e}")
            choice = input_fn("Retry? [y/N]: ").strip().lower()
            if choice in {"y", "yes"}:
                continue
            return None
        # Update in‑process allowed set and select the row
        cat_code = res["category"]["code"]
        allowed.add(cat_code)
        if res["created"]:
            print_fn(f"Created '{cat_code}'. Selected.")
        else:
            print_fn("Already exists; selecting it")
        return cat_code


def _select_category_for_group(
    *,
    session,
    allowed: set[str],
    chosen_default: str,
    selector: Callable[[Iterable[str], str], str] | None,
    allow_create_toggle: bool | None,
    input_fn: Callable[[str], str],
    print_fn: Callable[..., None],
) -> str:
    """Select (or create) a category for the current group.

    Encapsulates the interactive loop, injected selector path, creation intent
    handling, and validation against the allowed set. Loops until a valid
    category string is obtained.
    """
    options, default_category = _prepare_selector_inputs(
        allowed=allowed, default_category=chosen_default
    )
    allow_create = _is_creation_enabled(allow_create_toggle)

    while True:
        selected = _invoke_category_selector(
            selector=selector,
            allowed_options=options,
            default_category=default_category,
            allow_create=allow_create,
        )

        # Creation intent path
        if isinstance(selected, CreateCategoryRequest):
            result = _process_create_category_intent(
                session=session,
                intent=selected,
                chosen_default=default_category,
                allowed=allowed,
                input_fn=input_fn,
                print_fn=print_fn,
            )
            if result is None:
                # Cancel or retry exhausted: reopen the selector with prior default
                # and refreshed options (in case any categories were added elsewhere).
                options, default_category = _prepare_selector_inputs(
                    allowed=allowed, default_category=default_category
                )
                continue
            return result

        # Normal selection path
        if not isinstance(selected, str):
            raise TypeError(f"selector must return a string; got {type(selected).__name__}")
        resp_str = selected
        final_cat = default_category if not resp_str.strip() else resp_str.strip()
        if final_cat not in allowed:
            print_fn("Invalid category. Enter one of: " + ", ".join(options))
            # Refresh options in case allowed changed externally
            options, default_category = _prepare_selector_inputs(
                allowed=allowed, default_category=default_category
            )
            continue
        return final_cat


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------


def review_transaction_categories(
    transactions_with_categories: Iterable[CategorizedTransaction],
    *,
    source_provider: str,
    source_account: str | None,
    database_url: str | None = None,
    exemplars: int = 5,
    input_fn: Callable[[str], str] = builtins.input,
    print_fn: Callable[..., None] = builtins.print,
    selector: Callable[[Iterable[str], str], str] | None = None,
    allow_create: bool | None = None,
    auto_confirm_dupes: bool = False,
) -> list[CategorizedTransaction]:
    """Interactive review-and-persist flow for transaction categories.

    Behavior
    --------
    - Group input transactions primarily by a normalized merchant key. Two
      items are in the same group when their ``merchant`` values match ignoring
      case and internal whitespace. When ``merchant`` is empty/missing, the
      ``description`` field is used for the key. If both are empty, each item
      is treated as its own group (no merging by id/fingerprint).
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
        Deprecated. No longer used for category selection now that the
        prompt_toolkit completion menu is integrated. Retained for compatibility
        with previous signatures (and potential future prompts).
    print_fn:
        Function used to print output. Defaults to ``builtins.print``.

    Returns
    -------
    list[CategorizedTransaction]
        Finalized list reflecting the chosen category per input item.

    selector:
        Optional injection point for unit tests; when provided, it will be used
        to select the category instead of the interactive dropdown. The
        callable receives ``(allowed_categories, default_category)`` and must
        return the chosen category string.
    allow_create:
        When ``True`` (default), enables the “Create new category” path inside
        the interactive selector. Can be disabled in read‑only sessions.
    """

    # Materialize and precompute identifiers
    items, prepared = _materialize_and_prepare(
        transactions_with_categories, source_provider=source_provider
    )
    if not items:
        print_fn("No transactions to review.")
        return []

    groups_map = _build_groups(prepared)
    # Precompute a map from normalized merchant/description key -> positions.
    # Duplicate identity for this session is based on this key (see issue #48).
    by_key: dict[str, list[int]] = defaultdict(list)
    for i, prep in enumerate(prepared):
        k = _norm_merchant_key(prep.tx)
        if k is not None:
            by_key[k].append(i)
    final: list[CategorizedTransaction] = list(items)
    # Track positions already finalized via duplicate auto-apply to support
    # future scenarios where duplicates may span groups.
    assigned: set[int] = set()

    with session_scope(database_url=database_url) as session:
        allowed = _load_allowed_categories(session)
        if not allowed:
            raise RuntimeError("No categories present in fa_categories; cannot proceed")

        # Deterministic order by first index in each group
        group_roots = sorted(groups_map.keys(), key=lambda r: min(groups_map[r]))

        for root in group_roots:
            idxs = groups_map[root]
            # Skip or filter groups when some positions were already assigned
            # as duplicates of an earlier decision in this session.
            remaining = [i for i in idxs if i not in assigned]
            if not remaining:
                # A future group fully covered by earlier duplicate handling.
                print_fn("Duplicate(s) — skipping.")
                continue
            group_items = [prepared[i] for i in remaining]

            # Query duplicates for this group
            group_eids = [p.external_id for p in group_items if p.external_id is not None]
            group_fps = [p.fingerprint for p in group_items]
            db_dupes, db_default = _query_group_duplicates(
                session,
                source_provider=source_provider,
                source_account=source_account,
                group_eids=group_eids,
                group_fps=group_fps,
                exemplars=exemplars,
            )

            # Render summaries for the input group and DB duplicates
            _render_group_context(
                group_items=group_items,
                db_dupes=db_dupes,
                exemplars=exemplars,
                print_fn=print_fn,
            )

            chosen_default = _select_default_category(
                db_unanimous=db_default, group_items=group_items
            )
            print_fn(f"Proposed category: {chosen_default}")

            final_cat = _select_category_for_group(
                session=session,
                allowed=allowed,
                chosen_default=chosen_default,
                selector=selector,
                allow_create_toggle=allow_create,
                input_fn=input_fn,
                print_fn=print_fn,
            )

            _persist_group(
                session,
                source_provider=source_provider,
                source_account=source_account,
                group_items=group_items,
                final_cat=final_cat,
            )

            # Update result list
            for prep in group_items:
                final[prep.pos] = CategorizedTransaction(transaction=prep.tx, category=final_cat)

            # Commit the primary group immediately to avoid rolling it back if
            # duplicate persistence fails later.
            session.commit()
            print_fn("Saved.")

            # Session-duplicate handling (based on merchant/description key)
            # Look ahead for any remaining items whose normalized key matches
            # any item in this group. Offer to apply the chosen category to all
            # such duplicates now and skip their later review.
            group_keys = {
                k for k in (_norm_merchant_key(p.tx) for p in group_items) if k is not None
            }
            dupe_positions: list[int] = []
            for k in group_keys:
                for pos in by_key.get(k, []):
                    if pos in assigned or pos in remaining:
                        continue
                    # Only consider items that appear later in the queue (by pos)
                    # to match the "look ahead" behavior; equal/earlier positions
                    # are either part of this group or already processed.
                    if pos > max(remaining):
                        dupe_positions.append(pos)
            # De‑duplicate while preserving order (readable explicit loop)
            seen: set[int] = set()
            unique_dupe_positions: list[int] = []
            for p in dupe_positions:
                if p not in seen:
                    seen.add(p)
                    unique_dupe_positions.append(p)
            dupe_positions = unique_dupe_positions

            if dupe_positions:
                # Render a complete list per the requested copy
                print_fn("Session duplicates (all matches):")
                for pos in dupe_positions:
                    print_fn(f"  {_fmt_tx_row(prepared[pos].tx)}")
                # Prompt to apply now (default Yes) unless auto-confirm is set
                if auto_confirm_dupes:
                    choice_yes = True
                else:
                    prompt = (
                        f"Apply '{final_cat}' to these {len(dupe_positions)} duplicates "
                        "and skip their review? [Y/n]: "
                    )
                    resp = input_fn(prompt).strip().lower()
                    choice_yes = resp in {"", "y", "yes"}

                if choice_yes:
                    dupe_items = [prepared[p] for p in dupe_positions]
                    try:
                        _persist_group(
                            session,
                            source_provider=source_provider,
                            source_account=source_account,
                            group_items=dupe_items,
                            final_cat=final_cat,
                        )
                        for p in dupe_positions:
                            assigned.add(p)
                            final[p] = CategorizedTransaction(
                                transaction=prepared[p].tx, category=final_cat
                            )
                        session.commit()
                        print_fn("Saved duplicates.")
                    except Exception as e:  # pragma: no cover - defensive
                        session.rollback()
                        print_fn(f"Warning: failed to persist duplicates: {e}")

            # Blank line after handling this group (and any duplicates)
            print_fn("")

    return final


__all__ = ["review_transaction_categories"]
