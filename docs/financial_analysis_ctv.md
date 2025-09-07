Canonical Transaction View (CTV)
================================

Revised canonical schema used by `financial_analysis` normalizers. Adds a
`category` field and preserves provider-supplied category text verbatim when
present; otherwise `category = null`.

Exact field order and types

```
idx: integer (0-based position within the input collection after dropping non-transaction rows)
id: string | null
description: string | null
amount: string | null  # normalized string, 2 decimal places, ASCII dot decimal, leading minus for negatives
date: string | null    # YYYY-MM-DD
merchant: string | null
category: string | null
memo: string | null
```

Cross-cutting normalization rules
- CSV parsing: RFC 4180 compliant (UTF‑8; quoted fields may contain commas, doubled quotes, and embedded newlines).
- Row filtering and `idx`: skip headers, blank lines, and provider summary/non‑transaction rows; `idx` is the 0‑based index of remaining valid rows in original order.
- Amount polarity: cash‑flow view — outflows negative; inflows positive. Normalize formatting by stripping currency symbols/thousands separators; ensure exactly two decimals; keep a leading minus for negatives.
- Date: output as `YYYY‑MM‑DD`. No timezone conversion. When multiple date columns exist, follow provider rules below.
- Merchant vs description: `merchant` is the best available short counterparty; `description` is the human‑readable transaction line (may be longer). Follow provider rules below.
- IDs: use provider‑supplied IDs when present; otherwise `id = null`. Do not synthesize IDs in the CTV.
- Memo: preserve useful extra fields that don’t fit elsewhere; when joining multiple values, use `" | "` as a separator; preserve source line breaks where present.
- Currency: assume USD. If a non‑USD source appears later, prefix memo with `Currency=<CODE>; …`.
- Category: preserve provider‑supplied category strings verbatim when present; otherwise `category = null`. Do not infer categories.

Provider mappings (implemented)
- AMEX: `id=Reference`; `description=Appears On Your Statement As` (fallback `Description`); `amount=Amount` with canonical polarity (purchases negated); `date=Date` (MM/DD/YYYY); `merchant=Description`; `category=Category`; `memo=Extended Details + Address/City/State/Zip/Country + Card Member + Account # + (both description lines if they differ)`.
- Chase: `id=null`; `description=Description`; `amount=Amount` (already signed); `date=Post Date` (fallback `Transaction Date`); `merchant=Description`; `category=Category`; `memo=Type + Memo`.
- Alliant: `id=null`; `description=Description`; `amount=Amount` (parse `($… )` → negative; no inversion beyond that); `date=Date`; `merchant=null`; `category=null`; `memo=Description (+ Balance=… optional)`.
- Morgan Stanley: `id=null`; `description=Description` (multi‑line preserved); `amount=Amount($)` (strip quotes/commas; keep sign); `date=Transaction Date` (fallback `Activity Date`); `merchant=null`; `category=null`; `memo=Activity + Account + Institution Name + Memo + Tags`.
- Amazon Orders: `id=order id`; `description=first item from items` (append `+N more` when multiple); `amount=total` (always outflow → negative); `date=date` (YYYY‑MM‑DD); `merchant=Amazon.com`; `category=null`; `memo=order url + payments + non‑zero components among shipping, tax, gift, refund, shipping_refund as `key=value``.
- Venmo: `id=ID`; `description=Note` (emoji preserved; fallback `Type` with `Status`); `amount=Amount (total)` (respect `+`/`-`); `date=Datetime` date part; `merchant=From` if inflow (`+`), `To` if outflow (`-`); `category=null`; `memo=Status (when not Complete) + any non‑zero tip/tax/fee + Tax Rate/Tax Exempt + Funding Source + Destination`.

Out‑of‑scope (intentionally not implemented)
- Mapping Morgan Stanley Activity or Venmo Type to `category`.
- Merchant heuristics for Alliant or Morgan Stanley beyond the explicit rules above.
- Synthesizing IDs for providers lacking them (Chase, Alliant, Morgan Stanley).

Code reference
- CTV model: `financial_analysis/ctv.py::CanonicalTransaction`
- Normalizers: `financial_analysis/normalizers.py::CSVNormalizer`
