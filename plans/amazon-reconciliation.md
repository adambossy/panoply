# Amazon Purchase Reconciliation Module

## TL;DR

Build a reconciliation module that:
- Parses Amazon "payments" breakdown from normalized Amazon CTV rows to compute the actual card-charged amounts per order
- Matches those amounts to normalized CC CTV rows by amount (with tolerance) and date window, handling splits/refunds
- Outputs enriched CC transactions (still CanonicalTransaction) with real item details and order metadata

## Recommended Approach

### Step 0 — Shared Helpers

Extract shared helpers (`_to_decimal`, `_fmt_amount`, `_iso_datetime_date`) from `normalizers.py` into a new `utils/money_date.py` and import from there in both modules. Keep API identical to avoid churn.

### Step 1 — Data Model

Define light internal dataclasses (not exported outside module):

- **AmazonPaymentPart**: 
  - `instrument: str`
  - `amount: Decimal`
  - `kind: Literal["card","gift","promo","store_credit","unknown"]`

- **AmazonOrder**: 
  - `order_id: str`
  - `date: date`
  - `total: Decimal`
  - `payments: list[AmazonPaymentPart]`
  - `shipping: Decimal`
  - `tax: Decimal`
  - `refunds: list[Decimal]`
  - `order_url: str | None`
  - `items: list[str]`

- **ChargeEvent**: 
  - `order_id: str`
  - `date_window: tuple[date, date]`
  - `amount: Decimal`
  - `order_ref: AmazonOrder`
  - `type: Literal["charge","refund"]`
  - `split_index: int | None`
  - `split_count: int | None`

- **CcTxn**: Wraps CanonicalTransaction with parsed date, amount, description/merchant flags
  - `raw: CanonicalTransaction`
  - `date: date | None`
  - `amount: Decimal | None`
  - `is_amazonish: bool`

- **MatchResult**: 
  - `cc: CanonicalTransaction`
  - `order: AmazonOrder`
  - `allocation_amount: Decimal`
  - `charge_event: ChargeEvent`
  - `split_part: tuple[int, int] | None`
  - `match_confidence: float`
  - `reason: str`

### Step 2 — Input Parsing

**Amazon side (from normalized CTV):**

- Parse memo field to extract:
  - `payments=...` → parse to `[(instrument, amount)]` where instrument looks like "Visa 1234", "Mastercard ****1234", "Gift Card", "Rewards", "Promo", etc.
  - `shipping=`, `tax=`, `refund=`, `shipping_refund=` → decimals (optional; tolerate absence)
  
- Compute `card_portions = sum(amount for p in payments if p.kind == "card")`
  - If no payments section, assume `card_portions = total` (typical case)
  
- Create ChargeEvent(s) for each card portion:
  - **amount**: each card portion (can be one or multiple if Amazon charged multiple instruments)
  - **date_window**: `[order_date - 3 days, order_date + 10 days]`
    - Rationale: charge posts on ship/fulfillment; 10 days handles pre-order, split shipments; tweakable via options
  - For refunds (`refund>0` or `shipping_refund>0`), create Refund ChargeEvent(s) with `type="refund"` and positive amount to match to CC positive inflows
  
- **Items**: derive from description (first item +N more) or memo; keep a separate parsed list by splitting "items" column (if you have raw CSV for tests; for CTV we only have first item; that's OK for V1)

**CC side (from normalized CTV):**

- Parse amount (Decimal) and date (date)
- Heuristic `is_amazonish`: merchant/description contains any of `{"AMAZON", "AMZN", "AMZN MKTP", "AMAZON.COM", "AMZN DIGITAL"}` case-insensitive
  - Keep default on; can be disabled in options
- Only candidates marked amazonish are included by default to avoid false positives

### Step 3 — Matching Algorithm

**Pre-index:**
- Build date-buckets for CC candidates: `dict[date] → list[CcTxn]`
- Also index by amount: `dict[Decimal] → list[CcTxn]`, but we'll primarily use per-order candidate scans within date window

**Tolerance:**
- Use `abs diff ≤ $0.02` for direct amount matches (adjustable)

**Pass A: 1:1 direct matches**
- For each ChargeEvent amount A, scan CC transactions within date_window where sign matches (charge → negative on CC; refund → positive) and `|cc.amount| ≈ A` within tolerance
- If exactly one candidate → match
- If multiple candidates → choose nearest date; tie-breaker: description score (strings with "AMZN MKTP", then "AMAZON", then others), then smaller absolute difference, then earliest posting

**Pass B: Splits (order → multiple CC lines)**
- Some orders are split across shipments (two or three CC lines)
- For charge event A with no 1:1 match, search small subsets (size 2–3, limited) of CC candidates in the date window whose summed absolute amounts ≈ A within tolerance
  - DFS/backtracking with pruning; cap at N=50 candidate txns per window, but realistically much lower with amazonish filter
- If a split match found, assign `split_index/split_count` accordingly. Enrich each CC txn with "part of order" memo and per-part allocation

**Pass C: Merge (multiple small orders → one CC line)**
- Less common but happens when Amazon batches small digital orders
- For an unmatched CC amazonish txn with abs amount C, find combinations of small unmatched ChargeEvents whose totals ≈ C within tolerance
  - Limit search to K small events occurring within the CC date ±3 days and same account (if card filtering is enabled)

**Pass D: Refund reconciliation**
- For refund ChargeEvents, match to positive CC amazonish txns (same strategy as A/B but reversed sign)

**Stability:**
- Run matches deterministically: sort orders by (rarity of amount, then date)
  - Rarity = fewer CC candidates within window
  - This improves precision and reduces cross-day bleeding

### Step 4 — Output Enrichment

**For each matched CC txn:**

Return a new CanonicalTransaction with:
- **id**: keep original CC id (don't overwrite with order id to preserve bank provenance)
- **description**: first Amazon item + "+N more" (from Amazon CTV), or "Amazon order <order_id>"
- **merchant**: "Amazon.com"
- **amount**: unchanged (the actual posted CC amount)
- **date**: unchanged (the CC post date)
- **category**: keep original category if present, else None
- **memo**: append structured tags:
  - `AmazonReconciled=true`
  - `order_id=..., order_url=...`
  - `items_count=N, shipping=$, tax=$`
  - `allocation="$x of $total"` (for splits/merges)
  - `split="i/N"` when applicable

**For merged matches (one CC for multiple orders):**
- Mention all order_ids and combine item summaries concisely
  - Example: "3 orders: <first item>, <first item>, +1 more"

**Unmatched:**
- Leave unmatched CC txns unchanged
- Optionally return a side "report" object with unmatched Amazon orders and unmatched CC amazonish transactions for review (non-breaking optional return value or a separate function)

### Step 5 — Options

**AmazonReconcileOptions:**
- `date_window_days_before=3`
- `date_window_days_after=10`
- `amount_tolerance=Decimal("0.02")`
- `only_match_amazonish=True`
- `enable_split_matching=True`
- `enable_merge_matching=True`
- `card_hint: Optional[str]` (e.g., last4) to preferentially match payment parts for a specific card
  - If provided, only generate ChargeEvents from Amazon payments whose instrument contains the hint; otherwise, use all card parts
- `max_subset_size=3`
- `max_candidates_per_event=50`

## Rationale and Trade-offs

- **Parsing the Amazon "payments" breakdown is essential**: matching on order "total" alone is wrong when gift cards/promos/reward balances are used or when multiple instruments are used. Keeping it as parsing-from-memo avoids changing the existing normalizer contract.

- **Greedy + bounded subset search** is sufficient and simple for typical Amazon volumes; a full-blown global optimizer (Hungarian/ILP) is overkill now.

- **Enriching by emitting new CanonicalTransaction rows** (same schema) is the least invasive way to flow detail through existing pipelines; we avoid introducing new storage or schema changes.

- **A specialized internal type** helps organize data but we don't require public type changes yet.

## Risks and Guardrails

| Risk | Guardrail |
|------|-----------|
| Mis-match due to same-day same-amount collisions | Use "amazonish" filter, rarity-first ordering, and tie-breaker on nearest date and description tokens |
| Orders paid fully by gift card → no CC charge | `card_portion=0` → do not attempt to match |
| Refund timing can be weeks later | Larger window for refunds via options (allow override to ±45 days for refunds) |
| Rounding discrepancies and tax adjustments | `amount_tolerance` default 0.02, configurable |
| Multi-card payments | Prefer `card_hint` when provided; otherwise may produce ambiguous matches; surface low-confidence matches in report |
| International or non-USD | Assume USD only (per normalizers). Document as out-of-scope for V1 |

## When to Consider the Advanced Path

Consider more complexity when:
- You routinely see >200 Amazon CC lines per month, with frequent batching/splits causing many ambiguous candidates
- You need cross-account precision (multiple credit cards used on the same order) and provenance of instrument IDs
- You want full auditability and explainability with global optimal matching across the whole month
- You need to infer shipment-level allocations (not present in current export) or handle marketplace sellers' separate charges

## Optional Advanced Path (Outline)

- Promote "payments" to first-class fields in the Amazon normalizer output (rather than memo) so reconciliation doesn't rely on string parsing
- Add a global matching optimizer: formulate as bipartite matching with virtual nodes for split/merge, solved by MILP with penalties for date distance and string dissimilarity. Keep the greedy result as initialization
- Build a reconciliation report artifact (JSON) with confidence scores, conflicts, and a simple review UI to accept/override matches
- Persist linkage in an auxiliary table keyed by `(provider_txn_id, order_id, part_index)` to ensure idempotency across runs

## File/Module Structure

```
utils/money_date.py               # Shared helpers (to_decimal, fmt_amount, iso_date)
reconciliation/
  __init__.py
  amazon.py                       # Main reconciliation logic
tests/test_reconcile_amazon.py    # Scenario tests
```

### `reconciliation/amazon.py` API

```python
def parse_amazon_ctv_row(ctv: CanonicalTransaction) -> AmazonOrder: ...

def iter_charge_events(order: AmazonOrder, options) -> list[ChargeEvent]: ...

def is_amazonish(ctv: CanonicalTransaction) -> bool: ...

def reconcile_amazon(
    amz_ctvs: list[CanonicalTransaction],
    cc_ctvs: list[CanonicalTransaction],
    options=AmazonReconcileOptions()
) -> tuple[list[CanonicalTransaction], dict]:
    """
    Returns enriched CC CTVs (replacing originals one-for-one) and 
    optional report with unmatched/multiples.
    """
    ...

# Internal helpers:
def _find_direct_match(...): ...
def _find_split_match(...): ...
def _find_merge_match(...): ...
def _score_candidate(...): ...
```

## Matching Algorithm Details

### Parsing Payments

- Accept formats in memo: `"payments=Visa 1234:$10.50; Gift Card:$5.00"`
- Split by ';', strip, split on last ':' to separate instrument and amount
- Map instrument to kind:
  - if contains any of `{"Visa","Mastercard","Amex","Discover"}` → `kind="card"`
  - elif "Gift" → "gift"
  - elif any of `{"Rewards","Promo","Coupon"}` → "promo"
  - elif any of `{"Store Credit","Gift Balance"}` → "store_credit"

### Generation of ChargeEvents

- If any card parts: one event per card part
- Else if no payments parsed: one event for total
- Refund events: for each `refund/shipping_refund > 0`, create event `type="refund"` with `amount=that value`

### 1:1 Match Algorithm

```python
candidates = [
    cc for cc in cc_ctvs 
    if is_amazonish(cc) 
    and date in [start, end] 
    and sign(cc.amount) matches event.type 
    and |abs(cc.amount) - event.amount| <= tol 
    and cc not already matched
]
choose argmin(date_distance, description_score, abs_diff)
```

### Splits (size up to 3)

- Try combinations of unmatched candidates within window
- Prune by sum too big
- Stop early on exact tolerance fit

### Merge

- For each unmatched CC, find combination of unmatched ChargeEvents within tight window whose sum ≈ `abs(cc.amount)`
- Cap to small counts to avoid explosion

## Enrichment Examples

**1:1 match:**
```
description: "AirPods Pro +2 more"
memo: "AmazonReconciled=true | order_id=114-1234567-1234567 | allocation=$129.99 of $129.99 | shipping=$0.00 | tax=$10.80 | order_url=https://..."
```

**Split match:**
```
memo: "... | part_of_order=114-... | split=1/2 | allocation=$25.00 of $50.00"
```

**Merge match:**
```
memo: "orders=2 | order_ids=114-...,113-... | allocation=$14.99+$5.99=$20.98"
```

## Edge Cases to Handle

- **Gift-card-only orders**: no ChargeEvent; must not reconcile to any CC
- **Partial gift-card**: only card_portion is reconciled; leave gift part unrepresented (by design)
- **Multiple orders same amount same day**: pick nearest date/rarity first, leave any ambiguous unmatched for report rather than risking wrong match
- **Pre-orders**: allow long after-window (options override)
- **Refunds without prior match** (e.g., courtesy credit): still match to CC positive with memo "refund (no original match)"
- **Prime membership, Kindle/Audible**: included via amazonish heuristic; treat like any order with one item
- **Truncated items in normalized CTV**: show what's available; do not attempt to fetch more

## Testing Strategy

### Unit Tests

- `test_parse_payments_variants()`: different memo formats and instruments; malformed entries ignored
- `test_is_amazonish()`: various bank description strings
- `test_charge_event_generation()`: totals vs per-card parts; refunds

### Scenario Tests

- 1:1 normal purchase match
- Split charge across two CC postings same/adjacent days
- Merge: two small digital orders → one CC line
- Gift-card-only order → no match
- Partial gift card + card → only card portion matched
- Refund matched weeks later
- Ambiguous same-amount same-day → one matched, one left unmatched with report
- Multi-card order with card_hint restricts to correct account

### Golden Tests

- Feed a small month CSV (amazon + CC) and assert enriched CC output rows (ids unchanged, description/merchant/memo augmented)

### Property-ish Smoke

- Total of matched CC absolute amounts == sum of matched ChargeEvent amounts per order (within tolerance)

## Effort/Scope

- Shared helper extraction: S (~30–45 min)
- Module + parser + 1:1 matching: M (~1–3 h)
- Splits/merges + refunds + options + report: M-L (~3–6 h)
- Tests (unit + scenarios): M (~2–4 h)
- **Total: L (1–2 days)** for a polished, well-tested V1

## Signals to Revisit with More Complexity

- Frequent ambiguous matches or low-confidence rates (>5% unmatched/ambiguous per month)
- Multiple cards per order regularly used without card_hint
- Need end-to-end audit report or UI for manual resolution
