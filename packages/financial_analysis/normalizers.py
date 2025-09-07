"""CSV→CTV normalizers for AMEX, Chase, Alliant, Morgan Stanley, Amazon, Venmo.

Implements the revised normalization plan to emit Canonical Transaction View
records with a ``category`` field. Parsing follows RFC 4180 rules via the
stdlib :mod:`csv` module (UTF‑8, quoted fields with embedded commas and
newlines, doubled quotes).

Out of scope per spec: merchant heuristics for Alliant and Morgan Stanley,
deriving categories from non-category columns, currency handling beyond USD,
timezone conversion, and synthesizing IDs.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator, Sequence
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from io import StringIO

from .ctv import CanonicalTransaction

# ---------------------------------------------------------------------------
# Helpers (amount/date normalization, CSV loading)
# ---------------------------------------------------------------------------


def _to_decimal(raw: str | None) -> Decimal:
    if raw is None:
        raise ValueError("amount is required")
    s = raw.strip()
    if not s:
        raise ValueError("amount is empty")
    # Normalize sign/parentheses independently so combinations like
    # "-($1,234.56)" are handled robustly.
    negative = False

    # Iteratively strip leading sign, currency symbol, and surrounding
    # parentheses until stable. This supports any ordering of these markers.
    while True:
        changed = False
        if s.startswith("+"):
            s = s[1:].lstrip()
            changed = True
        elif s.startswith("-"):
            negative = True
            s = s[1:].lstrip()
            changed = True
        # Remove currency symbol early so cases like "$(1,234.56)" work
        if s.startswith("$"):
            s = s[1:].lstrip()
            changed = True
        # Surrounding parentheses indicate negativity regardless of sign.
        if s.startswith("(") and s.endswith(")") and len(s) >= 2:
            negative = True
            s = s[1:-1].strip()
            changed = True
        if not changed:
            break

    # Strip thousands separators; keep decimal point.
    s = s.replace(",", "").strip()

    try:
        d = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"invalid amount: {raw!r}") from exc
    return -abs(d) if negative else d


def _fmt_amount(d: Decimal) -> str:
    # Exactly two decimals; ASCII dot; leading minus for negatives.
    q = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # Use str() to avoid scientific notation.
    s = f"{q:.2f}"
    # Python formats -0.00 as '-0.00'—that's acceptable; keep sign semantics.
    return s


def _mmddyyyy_to_iso(date_str: str | None) -> str | None:
    if date_str is None:
        return None
    s = date_str.strip()
    if not s:
        return None
    # Some providers may include time in MM/DD/YYYY HH:MM; split on whitespace first
    first = s.split()[0]
    try:
        dt = datetime.strptime(first, "%m/%d/%Y")
    except ValueError as exc:
        raise ValueError(f"invalid MM/DD/YYYY date: {date_str!r}") from exc
    return dt.strftime("%Y-%m-%d")


def _iso_datetime_date(date_time: str | None) -> str | None:
    if date_time is None:
        return None
    s = date_time.strip()
    if not s:
        return None
    # Accept 'YYYY-MM-DD', 'YYYY-MM-DDTHH:MM:SS', and 'YYYY-MM-DD HH:MM:SS'.
    first = s.split()[0]
    return first.split("T", 1)[0]


def _first_non_empty(values: Sequence[str | None]) -> str | None:
    for v in values:
        if v is None:
            continue
        t = v.strip()
        if t:
            return t
    return None


def _read_csv_rows(csv_text: str) -> list[dict[str, str]]:
    # Use UTF-8; csv handles RFC 4180 quoting and embedded newlines.
    # Normalize newlines by using StringIO over the text as-is.
    with StringIO(csv_text) as f:
        reader = csv.DictReader(f)
        # Normalize header names by preserving them exactly (including spaces
        # and punctuation). DictReader already does this.
        rows: list[dict[str, str]] = []
        for row in reader:
            # DictReader may include a None key aggregating extra columns.
            # Filter out None keys entirely to preserve the declared
            # ``dict[str, str]`` shape and avoid leaking list values.
            normalized = {k: (v if v is not None else "") for k, v in row.items() if k is not None}
            rows.append(normalized)
        return rows


# ---------------------------------------------------------------------------
# Provider-specific normalizers
# ---------------------------------------------------------------------------


class CSVNormalizer:
    """Normalize provider CSV text into Canonical Transaction View rows.

    Usage
    -----
    rows = CSVNormalizer.normalize(provider="amex", csv_text=...)  # -> list[CanonicalTransaction]
    """

    @staticmethod
    def normalize(*, provider: str, csv_text: str) -> list[CanonicalTransaction]:
        p = provider.strip().lower().replace(" ", "_")
        rows = _read_csv_rows(csv_text)
        if p in {"amex", "american_express", "american-express"}:
            return list(_normalize_amex(rows))
        if p == "chase":
            return list(_normalize_chase(rows))
        if p == "alliant":
            return list(_normalize_alliant(rows))
        if p in {"morgan_stanley", "morgan-stanley", "ms"}:
            return list(_normalize_morgan_stanley(rows))
        if p in {"amazon", "amazon_orders", "amazon-orders"}:
            return list(_normalize_amazon_orders(rows))
        if p == "venmo":
            return list(_normalize_venmo(rows))
        raise ValueError(f"unknown provider: {provider!r}")


def _normalize_amex(rows: list[dict[str, str]]) -> Iterator[CanonicalTransaction]:
    # Headers (case-sensitive as exported):
    # Date, Description, Card Member, Account #, Amount, Extended Details,
    # Appears On Your Statement As, Address, City/State, Zip Code, Country,
    # Reference, Category
    idx = 0
    for r in rows:
        # Skip blank lines (all values empty)
        if all((v or "").strip() == "" for v in r.values()):
            continue
        raw_amount = (r.get("Amount") or "").strip()
        if not raw_amount:
            # Non-transaction rows shouldn't occur for AMEX, but skip defensively.
            continue
        # Parse and enforce canonical polarity: purchases (sample shows positive) -> negative.
        d = _to_decimal(raw_amount)
        canon = -abs(d) if d > 0 else abs(d)
        amount = _fmt_amount(canon)

        date = _mmddyyyy_to_iso(r.get("Date"))
        appears_as = (r.get("Appears On Your Statement As") or "").strip() or None
        descr = appears_as or (r.get("Description") or "").strip() or None
        merchant = (r.get("Description") or "").strip() or None
        tx_id = (r.get("Reference") or "").strip() or None
        category = (r.get("Category") or "").strip() or None

        # Memo composition
        memo_parts: list[str] = []
        ext = r.get("Extended Details") or ""
        if ext.strip():
            # Preserve multi-line text verbatim.
            memo_parts.append(ext.strip())
        for key in ("Address", "City/State", "Zip Code", "Country", "Card Member", "Account #"):
            val = (r.get(key) or "").strip()
            if val:
                memo_parts.append(f"{key}={val}")
        # Include both Description and Appears On* when they differ
        desc_short = (r.get("Description") or "").strip()
        if appears_as and desc_short and appears_as != desc_short:
            memo_parts.append(f"Description={desc_short}")
            memo_parts.append(f"AppearsAs={appears_as}")

        yield CanonicalTransaction(
            idx=idx,
            id=tx_id,
            description=descr,
            amount=amount,
            date=date,
            merchant=merchant,
            category=category,
            memo=" | ".join(memo_parts) if memo_parts else None,
        )
        idx += 1


def _normalize_chase(rows: list[dict[str, str]]) -> Iterator[CanonicalTransaction]:
    # Headers: Transaction Date, Post Date, Description, Category, Type, Amount, Memo
    idx = 0
    for r in rows:
        if all((v or "").strip() == "" for v in r.values()):
            continue
        amount = (r.get("Amount") or "").strip()
        if not amount:
            continue
        d = _to_decimal(amount)
        amount_str = _fmt_amount(d)

        post = r.get("Post Date")
        txn = r.get("Transaction Date")
        date = _mmddyyyy_to_iso(_first_non_empty([post, txn]))

        description = (r.get("Description") or "").strip() or None
        merchant = description
        category = (r.get("Category") or "").strip() or None

        memo_parts: list[str] = []
        typ = (r.get("Type") or "").strip()
        if typ:
            memo_parts.append(f"Type={typ}")
        extra = (r.get("Memo") or "").strip()
        if extra:
            memo_parts.append(extra)

        yield CanonicalTransaction(
            idx=idx,
            id=None,
            description=description,
            amount=amount_str,
            date=date,
            merchant=merchant,
            category=category,
            memo=" | ".join(memo_parts) if memo_parts else None,
        )
        idx += 1


def _normalize_alliant(rows: list[dict[str, str]]) -> Iterator[CanonicalTransaction]:
    # Headers: Date, Description, Amount, Balance
    idx = 0
    for r in rows:
        if all((v or "").strip() == "" for v in r.values()):
            continue
        raw_amount = (r.get("Amount") or "").strip()
        if not raw_amount:
            continue
        d = _to_decimal(raw_amount)
        amount_str = _fmt_amount(d)

        date = _mmddyyyy_to_iso(r.get("Date"))
        description = (r.get("Description") or "").strip() or None
        merchant = None  # heuristics deferred per spec
        category = None

        memo_parts: list[str] = []
        if description:
            memo_parts.append(description)
        bal = (r.get("Balance") or "").strip()
        if bal:
            memo_parts.append(f"Balance={bal}")

        yield CanonicalTransaction(
            idx=idx,
            id=None,
            description=description,
            amount=amount_str,
            date=date,
            merchant=merchant,
            category=category,
            memo=" | ".join(memo_parts) if memo_parts else None,
        )
        idx += 1


def _normalize_morgan_stanley(rows: list[dict[str, str]]) -> Iterator[CanonicalTransaction]:
    # Headers: Activity Date, Transaction Date, Account, Institution Name,
    # Activity, Description, Memo, Tags, Amount($)
    idx = 0
    for r in rows:
        if all((v or "").strip() == "" for v in r.values()):
            continue
        raw_amount = (r.get("Amount($)") or "").strip().strip('"')
        if not raw_amount:
            continue
        # Amount($) is quoted with thousands separators
        d = _to_decimal(raw_amount)
        amount_str = _fmt_amount(d)

        date = _mmddyyyy_to_iso(
            _first_non_empty([r.get("Transaction Date"), r.get("Activity Date")])
        )
        description = (r.get("Description") or "").strip() or None
        merchant = None  # heuristics deferred
        category = None  # do not map Activity to category per spec

        memo_parts: list[str] = []
        for key in ("Activity", "Account", "Institution Name", "Memo", "Tags"):
            val = (r.get(key) or "").strip()
            if val:
                memo_parts.append(f"{key}={val}")

        yield CanonicalTransaction(
            idx=idx,
            id=None,
            description=description,
            amount=amount_str,
            date=date,
            merchant=merchant,
            category=category,
            memo=" | ".join(memo_parts) if memo_parts else None,
        )
        idx += 1


def _normalize_amazon_orders(rows: list[dict[str, str]]) -> Iterator[CanonicalTransaction]:
    # Headers: order id, order url, items, to, date, total, shipping,
    # shipping_refund, gift, tax, refund, payments
    idx = 0
    for r in rows:
        if all((v or "").strip() == "" for v in r.values()):
            continue
        order_id = (r.get("order id") or "").strip()
        if not order_id:
            # Unexpected; skip rows without order id
            continue
        total_raw = (r.get("total") or "").strip()
        if not total_raw:
            continue
        total = _to_decimal(total_raw)
        amount_str = _fmt_amount(-abs(total))  # treat as outflow

        # Date is already YYYY-MM-DD in sample
        date = _iso_datetime_date(r.get("date"))

        # Description: first item, with optional "+N more"
        items_raw = (r.get("items") or "").strip()
        first_item = None
        if items_raw:
            # Items are separated by ';' with a trailing ';'
            parts = [p.strip() for p in items_raw.split(";")]
            parts = [p for p in parts if p]
            if parts:
                first_item = parts[0]
                if len(parts) > 1:
                    # Append "+N more" without an extra semicolon, per docs.
                    first_item = f"{first_item} +{len(parts) - 1} more"

        description = first_item or None
        merchant = "Amazon.com"
        category = None

        memo_parts: list[str] = []
        order_url = (r.get("order url") or "").strip()
        if order_url:
            memo_parts.append(f"order_url={order_url}")
        payments = (r.get("payments") or "").strip()
        if payments:
            memo_parts.append(f"payments={payments}")
        for key in ("shipping", "tax", "gift", "refund", "shipping_refund"):
            val = (r.get(key) or "").strip()
            if not val:
                continue
            try:
                dv = _to_decimal(val)
            except ValueError:
                continue
            if dv == 0:
                continue
            memo_parts.append(f"{key}={_fmt_amount(dv)}")

        yield CanonicalTransaction(
            idx=idx,
            id=order_id,
            description=description,
            amount=amount_str,
            date=date,
            merchant=merchant,
            category=category,
            memo=" | ".join(memo_parts) if memo_parts else None,
        )
        idx += 1


def _normalize_venmo(rows: list[dict[str, str]]) -> Iterator[CanonicalTransaction]:
    # Headers include a leading empty column in some exports.
    # Relevant columns: ID, Datetime, Type, Status, Note, From, To, Amount (total),
    # Amount (tip), Amount (tax), Amount (fee), Tax Rate, Tax Exempt, Funding Source, Destination,
    # Beginning Balance, Ending Balance
    idx = 0
    for r in rows:
        # Detect non-transaction summary rows: Beginning Balance but no ID
        id_val = (r.get("ID") or "").strip()
        dt_val = (r.get("Datetime") or "").strip()
        type_val = (r.get("Type") or "").strip()
        if not id_val or not dt_val or not type_val:
            # Also catches header/blank lines
            continue

        # Amount total like "+ $375.00" or "- $20.00"
        amt_raw = (r.get("Amount (total)") or "").strip()
        if not amt_raw:
            continue
        d = _to_decimal(amt_raw)
        amount_str = _fmt_amount(d)

        date = _iso_datetime_date(dt_val)

        note = (r.get("Note") or "").strip()
        status = (r.get("Status") or "").strip()
        description = note or f"{type_val}{(' (' + status + ')') if status else ''}"

        # Counterparty rule: inflow (+) -> From; outflow (-) -> To
        merchant = (r.get("From") if d >= 0 else r.get("To")) or None
        merchant = (merchant or "").strip() or None
        category = None

        memo_parts: list[str] = []
        if status and status.lower() != "complete":
            memo_parts.append(f"Status={status}")
        for key in ("Amount (tip)", "Amount (tax)", "Amount (fee)"):
            val = (r.get(key) or "").strip()
            if val:
                try:
                    dv = _to_decimal(val)
                except ValueError:
                    continue
                if dv != 0:
                    memo_parts.append(f"{key}={_fmt_amount(dv)}")
        for key in ("Tax Rate", "Tax Exempt", "Funding Source", "Destination"):
            val = (r.get(key) or "").strip()
            if val:
                memo_parts.append(f"{key}={val}")

        yield CanonicalTransaction(
            idx=idx,
            id=id_val,
            description=description,
            amount=amount_str,
            date=date,
            merchant=merchant,
            category=category,
            memo=" | ".join(memo_parts) if memo_parts else None,
        )
        idx += 1


__all__ = ["CSVNormalizer"]
