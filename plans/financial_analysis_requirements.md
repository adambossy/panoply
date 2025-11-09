# Financial Analysis Package - Detailed Requirements Specification

## TL;DR
This is a faithful, implementation-driven requirements specification for the financial_analysis package. It captures all observable behavior, interfaces, data flow, rules, and constraints embedded in the code so the system can be rebuilt with full fidelity.

## Recommended Approach (Simple Path)
Use this as the canonical spec. Rebuild features in this order: CSV→CTV ingest, taxonomy I/O, LLM categorization (batching + cache + parse), persistence, review UI, CLI commands. Preserve tunables, I/O formats, and error semantics verbatim.

---

## 1. Core Capabilities (Features and Workflows)

### LLM-Powered Categorization
- Categorize expense transactions into a two-level taxonomy using the OpenAI Responses API, model gpt-5.
- Batch processing by "exemplar groups" (grouped by normalized merchant/description). Only exemplars are sent to the LLM; group decisions are fanned out to all members.
- Strict JSON Schema enforced for model outputs, with allow-list of category codes drawn from the DB taxonomy.
- Parallel page execution with cache-backed idempotence.

### Caching (Page-Level)
- Cache one Responses call per "page of exemplars" with strong identity checks (dataset_id, page_size, page_index, settings hash, exemplar indices, and fingerprints).
- Atomic writes to disk under .cache or FA_CACHE_DIR.

### CSV→CTV Ingest (Normalization)
- Provider-specific CSV normalization to a Canonical Transaction View (CTV) record: {idx, id, description, amount, date, merchant, category, memo}.
- Implemented for AmEx, Chase, Alliant, Morgan Stanley, Amazon Orders, Venmo.
- Amount/date normalization with robust sign handling (including parentheses), numeric formatting (2 dp), and YYYY-MM-DD date extraction.

### Taxonomy Management
- Load taxonomy (fa_categories table) into a normalized two-level list: {code, display_name, parent_code}.
- Validate and create categories with server-side rules (case-insensitive duplication checks; parent must be a top-level category; allowed chars).

### Database Persistence
- Upsert transactions into fa_transactions by (source_provider, external_id) or fingerprint when id is absent.
- Apply category updates with optional confidence storage and verified gating.
- Auto-persist high-confidence suggestions (> 0.7) before interactive review.

### Duplicate Handling (DB-Backed)
- Query duplicates for a group by external ids and fingerprints within (source_provider, source_account). If non-null categories are unanimous, auto-apply them to the group.

### Interactive Review Workflow
- Group incoming transactions by normalized merchant/description; show summaries and DB duplicates; propose defaults; allow selecting/creating categories; optionally rename display_name; persist in committed batches per group.
- Confidence gate: only show low-confidence groups (effective score ≤ 0.7) in the UI.

### CLI
- **categorize-expenses**: CSV→CTV→categorize (optional persistence) and print id<TAB>category per row in input order.
- **review-transaction-categories**: end-to-end review flow with prefill, categorize unresolved, auto-apply high-confidence, then interactive review.

### Public API Surface
- api.categorize_expenses (re-export).
- api.review_transaction_categories (compat shim to review.review_transaction_categories).
- api.identify_refunds, api.partition_transactions, api.report_trends are interfaces only (NotImplemented).

---

## 2. Data Flow (Input to Output)

### categorize-expenses (CLI)
**Inputs**: 
- CSV path (AmEx Enhanced Details preferred; fallback to standard AmEx-like)
- OPENAI_API_KEY
- DB for taxonomy if present
- Optional persistence options

**Steps**:
1. Load .env; verify OPENAI_API_KEY.
2. Parse CSV → CTV (adapter selection, strict header checks).
3. Load taxonomy from DB (fa_categories).
4. Group transactions; select exemplars; build per-page payloads (page-relative idx).
5. For each page (parallel, cache-aware):
   - Build system + user prompts (taxonomy hierarchy + serialized CTV JSON).
   - Call OpenAI (gpt-5, Responses API, strict JSON schema).
   - Parse JSON; validate via Pydantic; map page idx back to exemplar absolute indices.
   - Cache page results.
6. Fan-out exemplar decisions to all group items → list[CategorizedTransaction].
7. If persist: upsert transactions; apply categories (source='llm').
8. Emit stdout lines: "<id>\t<category>" in original input order.

**Outputs**: 
- Textual lines on stdout
- Exit code 0 on success
- Errors to stderr with nonzero exit

### review-transaction-categories (CLI) / review_flow.review_categories_from_csv
**Inputs**: 
- CSV path
- DB URL
- source_provider/account
- allow_create toggle (CLI flag or FA_ALLOW_CATEGORY_CREATE)
- OPENAI_API_KEY (pre-required)

**Steps**:
1. CSV→CTV.
2. prefill_unanimous_groups_from_db: group by normalized merchant; query DB duplicates; if unanimous non-null category, persist group (category_source='rule') and collect prefilled positions/groups.
3. Unresolved subset only: load taxonomy; categorize with LLM (as above).
4. Auto-apply high confidence suggestions (> 0.7) to DB (only_unverified=True; per-item confidence).
5. Interactive review for low-confidence groups: show context, choose category (with create + optional rename), persist group (verified=True, category_source='manual'), commit each group.
6. Print concise status lines via on_progress; return the finalized list for reviewed (unresolved) items.

**Outputs**: 
- Finalized list[CategorizedTransaction] (for unresolved subset)
- on_progress messages
- DB updates

---

## 3. Business Rules (Explicit and Implicit)

### Input Validation
- CTV description must be a non-empty string after trim (fail-fast with idx and id context).
- page_size must be a positive integer (checked only when transactions are non-empty).
- Taxonomy for schema must include at least one non-blank code.
- Model outputs must conform to strict schema: required fields (idx, id, category, rationale, score, revised_* fields, citations) with types; score ∈ [0,1]; category ∈ allow-list. Out-of-taxonomy values are replaced with Other or Unknown if available and fallback enabled; otherwise error.

### Grouping (Categorize + Review)
- Primary key: normalized merchant value; fallback to description when merchant empty; normalize via NFKC, trim, collapse whitespace, casefold. Items with neither merchant nor description form their own singleton groups.

### Duplicate Analysis and Prefill
- Duplicate scope is (source_provider, source_account) with OR over group external_ids and group fingerprints.
- If all matches with non-null categories agree, persist that category for the whole group (category_source='rule') and mark positions prefilled.

### Confidence Semantics
- Effective score prefers revised_score when present; else score.
- Low-confidence threshold: ≤ 0.7 enters interactive review; > 0.7 is auto-applied (with only_unverified=True).

### Persistence Semantics
- Upsert: with external_id present, dedupe by (source_provider, external_id); else by fingerprint.
- apply_category_updates: supports only_unverified and use_item_confidence flags; category_source label recorded; categorized_at + updated_at timestamps set.
- persist_group: sets verified=True, category_source ∈ {'manual','rule'} only; optionally sets display_name + display_name_source='manual'.

### Category Creation
- Names trimmed; internal spaces collapsed; allowed chars: letters, numbers, spaces, and , & - /; length 1..64.
- Parent must exist and be a top-level category; display_name must be unique under the parent (case-insensitive). Code uniqueness is global case-insensitive. Returns {category: {...}, created: bool}.

### CSV Normalization (Provider-Specific)
- **AmEx**: positive purchases converted to negative outflows; Appears On… may override description; memo assembled from Extended Details and address-like fields; category column preserved if present.
- **Chase, Alliant, Morgan Stanley, Amazon Orders, Venmo**: per-provider header expectations, amount/date parsing, memo composition, merchant derivation (e.g., Venmo inflow uses From; outflow uses To; Amazon totals treated as outflow).

### CLI Output Contract
- One line per row in input order, formatted as "<id>\t<category>" (id may be empty string when missing).

### Error Handling Contracts (CLI)
- FileNotFoundError, PermissionError, csv.Error reported to stderr with specific messages; return 1. Missing OPENAI_API_KEY yields explicit stderr message and exit 1.

---

## 4. Technical Constraints, Tunables, and Dependencies

### Python and Environment
- Python 3.12
- .env loaded via python-dotenv
- Required env: OPENAI_API_KEY (always), DATABASE_URL (when DB used)
- Optional env: FA_CACHE_DIR; FA_ALLOW_CATEGORY_CREATE=0/1/true/false/yes/no

### LLM
- OpenAI SDK; Responses API; model="gpt-5"
- ResponseTextConfigParam with strict JSON Schema from taxonomy; no streaming
- Retries only on status 429 and 5xx; max attempts=3
- Backoff schedule (0.5s, 2.0s) with ±20% jitter
- Per-page client reuse across retries

### Batching and Parallelism
- Default page_size=10 (number of exemplar items per page)
- Concurrency=4; stop_on_error=True

### Caching
- Cache root: ./.cache by default or FA_CACHE_DIR
- Per-dataset directory: <root>/<dataset_id>/pages_ps<page_size>/<page_index>.json
- page_index is zero-padded to 5 digits
- Settings hash includes: model name; response_format; system instructions; CTV field order; normalized taxonomy
- Cache schema version=3

### Data Layer and Libraries
- SQLAlchemy ORM (FaCategory, FaTransaction), session management via db.client.session_scope
- prompt_toolkit for interactive UI (PromptSession; key bindings: Down, Tab, Enter; ghost suggestions; creation sentinel)
- promptorium for loading prompt template "fa-categorize"
- pydantic BaseModel for validation (strict / extra handling where specified)
- Typer for CLI, dotenv, pmap for parallel mapping, logging via logging_setup.get_logger

---

## 5. User Interactions (Commands and UX)

### Typer CLI App (module financial_analysis.cli)

#### categorize-expenses
**Required**: 
- `--csv-path PATH` (AmEx Enhanced Details or standard AmEx-like)

**Options**:
- `--persist` (bool): persist transactions and category updates
- `--database-url` (str | None): override DATABASE_URL
- `--source-provider` (str): default "amex"
- `--source-account` (str | None): optional account key for DB scoping

**Behavior**:
- Loads .env; requires OPENAI_API_KEY
- Reads CSV; validates headers; categorizes; optional persistence (upsert then category updates); prints "<id>\t<category>" lines
- Exit codes: 0 success; 1 on any error (explicit messages for missing env, file errors, CSV parse failure, taxonomy load failure, categorize failure, persistence failures)

#### review-transaction-categories
**Required**: 
- `--csv-path PATH`

**Options**:
- `--database-url` (str | None)
- `--source-provider` (default "amex")
- `--source-account` (str | None)
- `--allow-create` (bool | None): default is True; if omitted, env FA_ALLOW_CATEGORY_CREATE interpreted (0/false/no → False; 1/true/yes → True; other → None)

**Behavior**:
- Loads .env; requires OPENAI_API_KEY
- Delegates to review_flow.review_categories_from_csv, which prints progress lines and runs the end-to-end flow

### Interactive Review UI
- Category selection with dropdown (Down to open menu, Tab/Enter to complete/pick)
- Inline ghost suggestion for prefix matches
- Accept default with Enter on blank input
- Optional "+ Create new category…" option
- Creation path: prompt new category name (validated live), then parent selection (with "— Create as top-level —"), then commit
- May be disabled by allow_create=False
- Optional rename prompt for display_name when operator changes category; validates name; Esc cancels; Enter with blank keeps current name
- Summary line before review: "Auto-applied to X groups; Y low-confidence groups remain; largest size = Z"
- After saving a group: prints "Saved." and a blank line
- Duplicate groups detected in-session print "Duplicate(s) — skipping."

---

## 6. Data Models and Structures

### Canonical Transaction View (CTV)
**Fields** (strings or None): 
- idx
- id
- description
- amount (two-decimal string with sign)
- date (YYYY-MM-DD string)
- merchant
- category (pass-through from source if present)
- memo

idx is 0-based position after dropping non-transaction rows.

### TransactionRecord, Transactions, TransactionPartitions
- **TransactionRecord**: Mapping[str, Any] (opaque)
- **Transactions**: Iterable[TransactionRecord]
- **TransactionPartitions**: Iterable[Iterable[TransactionRecord]]

### CategorizedTransaction (dataclass)
- transaction: TransactionRecord
- category: str
- rationale: str (non-empty)
- score: float ∈ [0,1]
- optional revised_category/rationale/score
- optional citations

### LlmDecision (Pydantic)
- Mirrors CategorizedTransaction decision fields
- Strict validation, normalized citations

### Pagination and Cache DTOs (Pydantic)
- **PageExemplar**: {abs_index: int, fp: str}
- **PageItem**: {abs_index, details: LlmDecision}
- **PageCacheFile**: metadata + exemplars + items

### Duplicate Helpers
- **PreparedItem**: {pos, tx, external_id, fingerprint, suggested}

### PartitionPeriod (dataclass)
- years/months/weeks/days: optional positive ints
- At least one must be set
- Booleans disallowed

---

## 7. Integration Points

### OpenAI Responses API
- Model gpt-5
- JSON Schema via ResponseFormatTextJSONSchemaConfigParam
- Strict mode
- Retryable errors: 429 and 5xx only

### Database
- Session scope via db.client.session_scope
- ORM models FaTransaction, FaCategory (PostgreSQL)
- Persistence methods: upsert_transactions, apply_category_updates, auto_persist_high_confidence, duplicates.query_group_duplicates, duplicates.persist_group

### File System
- CSV reading (UTF-8), adapters for AmEx Enhanced Details or standard export
- Page cache read/write (+ atomic write using temp file and os.replace)

### Prompt and UI
- promptorium.load_prompt("fa-categorize") template
- prompt_toolkit for terminal interactions

### Env and CLI
- python-dotenv
- Typer-based CLI

---

## 8. Quality Requirements (Built-in Attributes)

### Determinism and Reproducibility
- Stable ordering of taxonomy and prompts
- Fixed CTV field order in JSON
- dataset_id includes fingerprints and settings hash
- page_index zero-padded for deterministic lexicographic order

### Performance and Scalability (Pragmatic)
- Parallel page execution (concurrency=4)
- Grouping reduces LLM calls by sending exemplars only
- Page-level caching avoids repeated calls

### Robustness
- Defensive validations (inputs, schema alignment, types, ranges)
- Strict schema for model outputs; controlled fallback for invalid categories
- Retry policy narrowly scoped to transient HTTP (429/5xx)
- Atomic cache writes; tolerant cache reads with strict identity checks

### Maintainability
- No side effects at import time
- Deferred/locals imports for DB-heavy modules
- Isolated prompting and parsing logic
- Tunables centralized

### Idempotency
- Upsert semantics in persistence layer
- Duplicate detection by fingerprint

### Logging
- Structured info log before LLM call per page (page index and count)
- Cache misses/hard failures logged at debug in cache module

---

## 9. Edge Cases and Special Scenarios

- Empty transaction list → categorize_expenses returns [] without validating page_size
- Missing OPENAI_API_KEY → explicit stderr and exit 1 (CLI)
- CSV header issues → informative csv.Error with missing column names; enhanced adapter fallback behavior; blank header rows
- Model output issues → ValueError for non-JSON / missing results / type mismatches / duplicate or missing idx; invalid scores; invalid categories without allowed fallback
- Cache inconsistencies → cache miss if schema_version/dataset_id/page_size/page_index/settings_hash mismatch; exemplar count/indices/fingerprints mismatch; items not 1:1 with exemplars
- Amounts formatting oddities → normalization supports "+", "-", "$", parentheses, commas, quotes; accounts for "-($1,234.56)" etc.
- Venmo non-transaction summary rows filtered (missing ID/Datetime/Type)
- Category creation collisions and parent constraints handled gracefully with clear errors; case-insensitive uniqueness
- Persistence flags: only_unverified prevents clobbering operator-reviewed categories
- Review confidence gating uses revised_score if present, else score; None treated as 0.0 (enters review)

---

## 10. Extension Points (Designed to be Extensible)

### Providers and Ingest
- Add new CSV providers by extending normalizers (or new ingest adapters)
- Keep CTV shape and normalization rules

### LLM Behavior
- Swap model name (_MODEL), adjust page_size, concurrency, retry schedule, jitter
- Update prompt template (fa-categorize)
- All changes roll cache via settings hash

### Taxonomy and Validation
- DB-backed taxonomy is authoritative
- Extend schema in DB
- The app derives allow-list and prompt display automatically

### Persistence Policy
- Adjust high-confidence threshold
- Tweak only_unverified/use_item_confidence flags
- Add new category_source labels by extending allowed set (currently {'manual','rule'} in duplicates.persist_group)

### CLI Surface
- Implement missing interfaces (identify-refunds, partition-transactions, report-trends) using models.PartitionPeriod and RefundMatch contracts
- Add output formats (CSV/JSON/table) while preserving existing "<id>\t<category>" default for categorize-expenses

### UI Customization
- Inject selector callable for tests
- Change allow_create default via env
- Tweak key bindings and suggestion behavior in term_ui

### Caching and Storage
- Move cache root via FA_CACHE_DIR
- Change schema version on on-disk shape changes
- Extend cache payloads carefully

---

## Rationale and Trade-offs

The design optimizes for minimizing LLM calls (group-based exemplar strategy), deterministic behavior (strict schema and stable ordering), and operational safety (idempotent DB writes, atomic cache). Alternatives like per-transaction calls or streaming responses are unnecessary for current scope and would increase cost/complexity.

---

## Risks and Guardrails

- **Taxonomy drift**: any change to codes/parentage must roll the cache (already covered via settings hash)
- **Model output variability**: strict schema and fallback-to-Other mitigate; keep retry policy narrow to avoid masking parse bugs
- **Database coupling**: ensure DATABASE_URL set and migrations applied; loader raises clear errors when categories are missing
- **UI dependencies**: prompt_toolkit availability; allow non-interactive selector for tests

---

## When to Consider the Advanced Path

- Very large datasets (thousands of unique merchants) causing long LLM pages or parallelism saturation
- Need for multi-provider ingest orchestration with schema detection beyond AmEx adapters
- Online/daemonized flows, streaming UIs, or remote cache stores
- Human-in-the-loop analytics (audit trails, rationale review UIs) beyond terminal

---

## Optional Advanced Path (Brief)

- Introduce a provider-agnostic ingest registry and schema inference
- Add batched persistence with bulk upserts and conflict reporting
- Support configurable model/prompt variants with versioned policy bundles
- Expose a JSON/CSV report generator for trends and quality metrics (coverage, confidence, drift)
