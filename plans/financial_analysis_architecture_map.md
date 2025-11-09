# Financial Analysis Package - Architecture Map

## Complete File-by-File Interface and Dependency Reference

---

## packages/financial_analysis/__init__.py

**Purpose**: Package public import surface; re-exports stable API functions, models, and utility classes.

**External Interface (exported symbols)**:
```python
__all__ = [
    "categorize_expenses",
    "identify_refunds",
    "partition_transactions",
    "report_trends",
    "review_transaction_categories",
    "TransactionRecord",
    "CategorizedTransaction",
    "RefundMatch",
    "PartitionPeriod",
    "Transactions",
    "TransactionPartitions",
    "CanonicalTransaction",
    "CSVNormalizer"
]
```

**Callers**: None internally (intended for external consumers to import from `financial_analysis`).

**Dependencies**: 
- `.api` (identify_refunds, partition_transactions, report_trends, review_transaction_categories)
- `.categorize` (categorize_expenses)
- `.ctv` (CanonicalTransaction)
- `.models` (TransactionRecord, CategorizedTransaction, RefundMatch, PartitionPeriod, Transactions, TransactionPartitions)
- `.normalizers` (CSVNormalizer)

**Data Structures**: Consumes exported dataclasses and Pydantic models from `.models` and `.ctv`.

---

## packages/financial_analysis/api.py

**Purpose**: Public API layer and compatibility shims; re-exports categorize_expenses and the review workflow; other interfaces are stubs.

**External Interface (exported symbols)**:
- `categorize_expenses` (re-export)
- `OpenAI` (re-export/alias)
- `identify_refunds` (stub - raises NotImplementedError)
- `partition_transactions` (stub - raises NotImplementedError)
- `report_trends` (stub - raises NotImplementedError)
- `review_transaction_categories` (delegates to `.review`)
- `review_categories_from_csv` (re-export from `.workflows.review_flow`)

**Callers**: 
- `packages/financial_analysis/__init__.py` (re-exports)
- `packages/financial_analysis/cli.py` (dynamic import of review_categories_from_csv)

**Dependencies**: 
- `collections.abc.Iterable`
- `openai.OpenAI`
- `.categorize.categorize_expenses`
- `.models` (CategorizedTransaction, PartitionPeriod, RefundMatch, TransactionPartitions, Transactions)
- `.workflows.review_flow.review_categories_from_csv`
- Local import of `.review.review_transaction_categories` in the shim

**Data Structures**: Consumes `.models` types (CategorizedTransaction, PartitionPeriod, etc.). No new models defined.

---

## packages/financial_analysis/cache.py

**Purpose**: Page-level cache utilities keyed by dataset and prompt/taxonomy settings; compute_dataset_id; read/write cached page results.

**External Interface (exported symbols)**:
- `SCHEMA_VERSION` (constant = 3)
- `compute_dataset_id(transactions, taxonomy) -> str`
- `read_page_from_cache(dataset_id, page_size, page_index, settings_hash, exemplars) -> PageCacheFile | None`
- `write_page_to_cache(dataset_id, page_size, page_index, settings_hash, exemplars, items) -> None`

**Callers**: 
- `packages/financial_analysis/categorize.py` (page cache I/O)
- `compute_dataset_id` used by categorize

**Dependencies**: 
- `hashlib`, `json`, `os`, `re`, `pathlib.Path`
- `collections.abc` (Iterable, Mapping, Sequence)
- `typing.Any`
- `.prompting` (build_response_format, build_system_instructions, CTV_FIELD_ORDER)
- `.logging_setup.get_logger`
- `.models` (LlmDecision, PageCacheFile, PageExemplar, PageItem)
- `.persistence.compute_fingerprint`

**Data Structures**: 
- Consumes Pydantic models: `PageCacheFile`, `PageExemplar`, `PageItem`, `LlmDecision` for strict cache schema
- Defines `SCHEMA_VERSION` constant
- Dataset-id regex pattern

---

## packages/financial_analysis/categorization.py

**Purpose**: Input validation (CTV descriptions) and strict parsing/alignment of LLM responses (simple list and detailed variants).

**External Interface (exported symbols)**:
- `ensure_valid_ctv_descriptions(transactions: Sequence[Mapping[str, Any]]) -> None`
- `parse_and_align_categories(response_text: str, item_count: int, allowed_categories: Sequence[str]) -> list[str]`
- `parse_and_align_category_details(response_text: str, items: Sequence[Mapping[str, Any]], allowed_categories: Sequence[str], fallback_to_other: bool = True) -> list[LlmDecision]`

**Callers**: 
- `packages/financial_analysis/categorize.py` (pre-request validation and response parsing)

**Dependencies**: 
- `collections.abc` (Mapping, Sequence)
- `typing.Any`
- `pydantic` (BaseModel, ConfigDict, ValidationInfo, field_validator)

**Data Structures**: 
- Defines Pydantic models `_DetailItem` and `_DetailBody` (internal) for strict validation of detailed results
- Consumes allowed_categories lists provided by callers

---

## packages/financial_analysis/categorize.py

**Purpose**: Core categorization flow using OpenAI Responses API with grouping, paging, caching, and fan-out to all group members; includes DB-prefill helper.

**External Interface (exported symbols)**:
- `categorize_expenses(transactions: Transactions, taxonomy: Iterable[Mapping[str, Any]], page_size: int = 10, source_provider: str = "amex") -> list[CategorizedTransaction]`
- `prefill_unanimous_groups_from_db(ctv_items: list[Mapping[str, Any]], database_url: str | None, source_provider: str, source_account: str | None) -> tuple[set[int], dict[int, str]]` (used by workflows)
- `PageResult` (NamedTuple)

**Callers**: 
- `packages/financial_analysis/api.py` (re-export of categorize_expenses)
- `packages/financial_analysis/cli.py` (invokes categorize_expenses)
- `packages/financial_analysis/workflows/review_flow.py` (uses categorize_expenses and prefill_unanimous_groups_from_db)
- `packages/financial_analysis/cache.py` (lazy import of _MODEL inside _settings_hash)

**Dependencies**: 
- `json`, `math`, `random`, `time`, `unicodedata`
- `collections.abc` (Iterable, Mapping, Sequence)
- `typing` (Any, NamedTuple, cast)
- `openai.OpenAI`
- `openai.types.responses.ResponseTextConfigParam`
- `pmap.p_map`
- `.prompting` (serialize_ctv_to_json via build_user_content, build_system_instructions, build_response_format)
- `.cache` (compute_dataset_id, read_page_from_cache, write_page_to_cache)
- `.categorization` (ensure_valid_ctv_descriptions, parse_and_align_category_details)
- `.logging_setup.get_logger`
- `.models` (CategorizedTransaction, LlmDecision, Transactions)
- Local/lazy: `db.client.session_scope`, `.duplicates` (PreparedItem, persist_group, query_group_duplicates), `.persistence.compute_fingerprint`

**Data Structures**: 
- Defines `PageResult` (NamedTuple)
- Consumes `CategorizedTransaction` and `LlmDecision` models for typed results
- Uses strict JSON schema via prompting
- Uses group mapping structures (lists/dicts)

---

## packages/financial_analysis/categories.py

**Purpose**: Category domain helpers and DB-backed operations (create/list), plus name normalization/validation; taxonomy loader.

**External Interface (exported symbols)**:
```python
__all__ = [
    "normalize_name",
    "validate_name",
    "createCategory",
    "create_category",
    "list_top_level_categories",
    "load_taxonomy_from_db",
    "NameValidation",
    "CategoryDict",
    "CreateCategoryResult"
]
```

**Public functions**:
- `normalize_name(name: str) -> str`
- `validate_name(name: str) -> NameValidation`
- `createCategory(session, display_name, parent_code=None) -> CreateCategoryResult` (alias create_category)
- `list_top_level_categories(session) -> list[CategoryDict]`
- `load_taxonomy_from_db(database_url: str | None = None) -> list[dict[str, Any]]`

**Dataclasses/TypedDicts**:
- `NameValidation` (dataclass)
- `CategoryDict` (TypedDict)
- `CreateCategoryResult` (TypedDict)

**Callers**: 
- `packages/financial_analysis/cli.py` (load_taxonomy_from_db)
- `packages/financial_analysis/review.py` (createCategory, list_top_level_categories)
- `packages/financial_analysis/term_ui.py` (validate_name)
- `packages/financial_analysis/workflows/review_flow.py` (load_taxonomy_from_db)

**Dependencies**: 
- `re`
- `dataclasses.dataclass`
- `typing` (Any, TypedDict)
- `db.client.session_scope`
- `db.models.finance.FaCategory`
- `sqlalchemy` (func, select)
- `sqlalchemy.exc.IntegrityError`
- `sqlalchemy.orm.Session`

**Data Structures**: 
- Defines `NameValidation` (dataclass), `CategoryDict` and `CreateCategoryResult` (TypedDicts)
- Consumes ORM model `FaCategory`

---

## packages/financial_analysis/cli.py

**Purpose**: Typer-based CLI exposing categorize, partition, refunds, and review commands; shells around API and workflows.

**External Interface (exported symbols)**:
- `main` (stub)
- `cmd_categorize_expenses`
- `cmd_identify_refunds` (stub)
- `cmd_partition_transactions` (stub)
- `categorize_expenses_cmd` (Typer command)
- `review_transaction_categories_cmd` (Typer command)
- `CSV_PATH_OPTION`
- `app` (Typer)

**Callers**: None internally (entrypoint module). Invokes financial_analysis APIs and workflows.

**Dependencies**: 
- `pathlib.Path`
- `typing` (Annotated, Any)
- `typer` (Typer, Option)
- `dotenv.load_dotenv`
- `typer.models.OptionInfo`
- `csv`, `os`, `sys` (inside functions)
- `.categories.load_taxonomy_from_db`
- `.categorize.categorize_expenses`
- `.ingest.adapters.amex_enhanced_details_csv.to_ctv_enhanced_details`
- `.ingest.adapters.amex_like_csv.to_ctv`
- Dynamic import of `.api.review_categories_from_csv`
- `db.client.session_scope`
- `.persistence` (upsert_transactions, apply_category_updates)

**Data Structures**: 
- Consumes `CategorizedTransaction` indirectly via categorize_expenses return
- Prints tab-delimited output
- No new models

---

## packages/financial_analysis/ctv.py

**Purpose**: Canonical Transaction View dataclass representing normalized transaction rows with fixed field order.

**External Interface (exported symbols)**:
```python
__all__ = ["CanonicalTransaction"]
```

**Class**: `CanonicalTransaction` (frozen dataclass)

**Callers**: 
- `packages/financial_analysis/normalizers.py`
- `packages/financial_analysis/__init__.py` (re-export)

**Dependencies**: 
- `dataclasses.dataclass`

**Data Structures**: 
Defines `CanonicalTransaction` (frozen dataclass with fields: idx, id, description, amount, date, merchant, category, memo)

---

## packages/financial_analysis/duplicates.py

**Purpose**: Shared duplicate detection and persistence helpers used by review and categorize (prefill path).

**External Interface (exported symbols)**:
```python
__all__ = ["PreparedItem", "query_group_duplicates", "persist_group"]
```

**Functions**:
- `query_group_duplicates(session, source_provider, source_account, external_ids, fingerprints) -> list[FaTransaction]`
- `persist_group(session, items, category_code, source, display_name=None) -> None`

**Dataclass**: `PreparedItem`

**Callers**: 
- `packages/financial_analysis/review.py`
- `packages/financial_analysis/categorize.py`

**Dependencies**: 
- `collections.abc` (Iterable, Mapping)
- `dataclasses.dataclass`
- `typing.Any`
- `db.models.finance.FaTransaction`
- `sqlalchemy` (distinct, func, or_, select, update)
- `sqlalchemy.orm.Session`
- `.persistence.upsert_transactions`

**Data Structures**: 
- Defines `PreparedItem` (dataclass)
- Consumes `FaTransaction` ORM model

---

## packages/financial_analysis/logging_setup.py

**Purpose**: Centralized logging configuration and safe logger acquisition for library use.

**External Interface (exported symbols)**:
- `configure_logging(level=None, fmt=None, stream=...) -> None`
- `get_logger(name: str) -> logging.Logger`

**Callers**: 
- `packages/financial_analysis/cache.py`
- `packages/financial_analysis/categorize.py`

**Dependencies**: 
- `logging`, `os`, `sys`, `threading`
- `typing.IO`

**Data Structures**: 
- Internal module-level state (_CONFIGURED flag, locks)
- No exported models

---

## packages/financial_analysis/models.py

**Purpose**: Core data models and type aliases for transactions, categorization results, partitioning periods, and page-cache DTOs.

**External Interface (exported symbols)**:

**Type Aliases**:
- `TransactionRecord = Mapping[str, Any]`
- `Transactions = Iterable[TransactionRecord]`
- `TransactionPartitions = Iterable[Iterable[TransactionRecord]]`

**Dataclasses**:
- `CategorizedTransaction` (with rationale/score and optional revised_*)
- `PartitionPeriod` (with validation)

**NamedTuple**:
- `RefundMatch`

**Pydantic Models**:
- `LlmDecision`
- `PageExemplar`
- `PageItem`
- `PageCacheFile`

**Callers**: 
- `packages/financial_analysis/api.py`
- `packages/financial_analysis/cache.py`
- `packages/financial_analysis/categorize.py`
- `packages/financial_analysis/persistence.py`
- `packages/financial_analysis/review.py`
- `packages/financial_analysis/__init__.py`

**Dependencies**: 
- `collections.abc` (Iterable, Mapping)
- `dataclasses.dataclass`
- `typing` (Any, NamedTuple)
- `pydantic` (BaseModel, ConfigDict, field_validator)

**Data Structures**: 
All defined in this module (see External Interface above)

---

## packages/financial_analysis/normalizers.py

**Purpose**: CSV-to-CTV normalization for multiple providers; emits CanonicalTransaction objects.

**External Interface (exported symbols)**:
```python
__all__ = ["CSVNormalizer"]
```

**Class**: `CSVNormalizer` with static method:
- `normalize(provider: str, csv_text: str) -> list[CanonicalTransaction]`

**Callers**: 
- `packages/financial_analysis/__init__.py` (re-export)
- Not used elsewhere in provided code

**Dependencies**: 
- `csv`
- `collections.abc` (Iterator, Sequence)
- `datetime`
- `decimal` (Decimal, ROUND_HALF_UP, InvalidOperation)
- `io.StringIO`
- `.ctv.CanonicalTransaction`

**Data Structures**: 
- Produces `CanonicalTransaction` instances
- Internal helper functions only

---

## packages/financial_analysis/persistence.py

**Purpose**: Persistence integration with shared DB for upserting transactions and applying category updates; fingerprint computation; auto-apply high-confidence.

**External Interface (exported symbols)**:
```python
__all__ = [
    "compute_fingerprint",
    "upsert_transactions",
    "apply_category_updates",
    "auto_persist_high_confidence"
]
```

**Functions**:
- `compute_fingerprint(transaction: Mapping[str, Any]) -> str`
- `upsert_transactions(session, transactions, source_provider, source_account=None) -> None`
- `apply_category_updates(session, categorized_transactions, source_provider, use_item_confidence=False, only_unverified=False) -> None`
- `auto_persist_high_confidence(categorized_transactions, database_url, source_provider, source_account=None) -> None`

**Callers**: 
- `packages/financial_analysis/cache.py` (compute_fingerprint)
- `packages/financial_analysis/duplicates.py` (upsert_transactions)
- `packages/financial_analysis/categorize.py` (compute_fingerprint in prefill)
- `packages/financial_analysis/review.py` (compute_fingerprint)
- `packages/financial_analysis/workflows/review_flow.py` (auto_persist_high_confidence)
- `packages/financial_analysis/cli.py` (upsert_transactions, apply_category_updates)

**Dependencies**: 
- `hashlib`, `json`
- `collections.abc` (Iterable, Mapping)
- `datetime.date`
- `decimal` (Decimal, ROUND_HALF_UP, InvalidOperation)
- `typing.Any`
- `sqlalchemy` (func, update)
- `sqlalchemy.dialects.postgresql.insert`
- `sqlalchemy.orm.Session`
- `db.models.finance.FaTransaction`
- `.models.CategorizedTransaction`

**Data Structures**: 
- Fingerprint algorithm over normalized fields
- Consumes `CategorizedTransaction` dataclass
- Operates on `FaTransaction` ORM model

---

## packages/financial_analysis/prompting.py

**Purpose**: Prompt construction (system and user content), deterministic CTV JSON serialization, and strict response_format schema for OpenAI Responses API.

**External Interface (exported symbols)**:
- `CTV_FIELD_ORDER` (tuple)
- `serialize_ctv_to_json(ctv_items: Sequence[Mapping[str, Any]]) -> str`
- `build_system_instructions() -> str`
- `build_user_content(ctv_json: str, taxonomy: Sequence[Mapping[str, Any]]) -> str`
- `build_response_format(taxonomy: Sequence[Mapping[str, Any]]) -> ResponseFormatTextJSONSchemaConfigParam`

**Callers**: 
- `packages/financial_analysis/cache.py`
- `packages/financial_analysis/categorize.py`

**Dependencies**: 
- `json`
- `collections.abc` (Mapping, Sequence)
- `typing.Any`
- `openai.types.responses.ResponseFormatTextJSONSchemaConfigParam` (typing target)
- `promptorium.load_prompt`

**Data Structures**: 
- Defines `CTV_FIELD_ORDER`
- Builds JSON Schema object for Responses API

---

## packages/financial_analysis/review.py

**Purpose**: Interactive review workflow to confirm/override categories and persist to DB; grouping by normalized merchant/description; supports optional creation/rename.

**External Interface (exported symbols)**:
```python
__all__ = ["review_transaction_categories"]
```

**Function**:
- `review_transaction_categories(ctv_items: list[Mapping[str, Any]], database_url: str | None, source_provider: str, source_account: str | None, allow_create: bool | None, selector: Callable | None = None) -> list[CategorizedTransaction]`

**Callers**: 
- `packages/financial_analysis/api.py` (compatibility shim import)
- `packages/financial_analysis/workflows/review_flow.py` (invokes directly)

**Dependencies**: 
- `builtins`, `unicodedata`
- `collections.Counter`, `collections.defaultdict`
- `collections.abc` (Callable, Iterable, Mapping)
- `typing.Any`
- `db.client.session_scope`
- `db.models.finance.FaCategory`
- `sqlalchemy.select`
- `sqlalchemy.exc.SQLAlchemyError`
- `.categories` (createCategory, list_top_level_categories)
- `.duplicates` (PreparedItem, persist_group, query_group_duplicates)
- `.models.CategorizedTransaction`
- `.persistence.compute_fingerprint`
- `.term_ui` (TOP_LEVEL_SENTINEL, CreateCategoryRequest, prompt_new_category_name, prompt_new_display_name, prompt_select_parent, select_category_or_create)

**Data Structures**: 
- Defines internal `_DisjointSet` (union-find) used earlier (current grouping uses normalized merchant)
- Consumes `PreparedItem` dataclass, `CategorizedTransaction`
- Uses sentinel/constants from term_ui

---

## packages/financial_analysis/term_ui.py

**Purpose**: Small prompt_toolkit-based terminal UI helpers for category selection and optional creation/rename with validation.

**External Interface (exported symbols)**:
```python
__all__ = [
    "select_category_or_create",
    "prompt_new_category_name",
    "prompt_new_display_name",
    "prompt_select_parent",
    "CreateCategoryRequest",
    "CREATE_SENTINEL",
    "TOP_LEVEL_SENTINEL"
]
```

**Class**: `CreateCategoryRequest`

**Functions**:
- `select_category_or_create(choices: Iterable[str], default: str | None, allow_create: bool) -> str | CreateCategoryRequest`
- `prompt_new_category_name() -> str`
- `prompt_select_parent(top_level_categories: Sequence[Mapping[str, Any]]) -> str | None`
- `prompt_new_display_name(current_name: str) -> str | None`

**Constants**: 
- `CREATE_SENTINEL`
- `TOP_LEVEL_SENTINEL`

**Callers**: 
- `packages/financial_analysis/review.py`

**Dependencies**: 
- `inspect`
- `collections.abc` (Iterable, Sequence)
- `typing.Any`
- `prompt_toolkit` (PromptSession)
- `prompt_toolkit.auto_suggest` (AutoSuggest, Suggestion)
- `prompt_toolkit.completion.WordCompleter`
- `prompt_toolkit.key_binding.KeyBindings`
- `prompt_toolkit.styles.Style`
- `prompt_toolkit.validation` (ValidationError, Validator)
- `.categories.validate_name`

**Data Structures**: 
- Defines `CreateCategoryRequest` (simple wrapper class)
- Consumes `categories.validate_name` for validation

---

## packages/financial_analysis/workflows/review_flow.py

**Purpose**: Orchestrates CSV → CTV ingest, DB-based prefill, categorization of unresolved items, auto-persistence of high-confidence suggestions, and interactive review.

**External Interface (exported symbols)**:
```python
__all__ = ["review_categories_from_csv"]
```

**Function**:
- `review_categories_from_csv(csv_path: str | PathLike, database_url: str | None = None, source_provider: str = "amex", source_account: str | None = None, allow_create: bool | None = None, on_progress: Callable[[str], None] | None = None) -> list[CategorizedTransaction]`

**Callers**: 
- `packages/financial_analysis/api.py` (re-export)
- `packages/financial_analysis/cli.py` (indirectly via api)

**Dependencies**: 
- `collections.abc.Callable`, `collections.abc.Mapping`
- `os.PathLike`
- `pathlib.Path`
- `typing.Any`
- `..categories.load_taxonomy_from_db`
- `..categorize` (categorize_expenses, prefill_unanimous_groups_from_db)
- `..models.CategorizedTransaction`
- `..persistence.auto_persist_high_confidence`
- `..review.review_transaction_categories`
- Local CSV adapters: `..ingest.adapters.amex_enhanced_details_csv.to_ctv_enhanced_details` and `..ingest.adapters.amex_like_csv.to_ctv` (via helper _read_ctv_from_csv)
- `db.client.session_scope`

**Data Structures**: 
- Consumes `CategorizedTransaction`
- Operates over raw CTV mappings (list[Mapping[str, Any]])

---

## packages/financial_analysis/ingest/seed_taxonomy.py

**Purpose**: Script to (re)seed the two-level category taxonomy into fa_categories from a JSON file.

**External Interface (exported symbols)**:
- `reseed_taxonomy(database_url: str, file: Path) -> None`
- `main(argv: list[str] | None = None) -> None`

(Script-style; no __all__.)

**Callers**: None internally (CLI/utility).

**Dependencies**: 
- `argparse`, `json`
- `pathlib.Path`
- `typing.Any`
- `db.client.session_scope`
- `db.models.finance.FaCategory`
- `sqlalchemy.text`
- `dotenv.load_dotenv` (best-effort in helper)

**Data Structures**: 
- Consumes ORM model `FaCategory`
- Operates on JSON file list structure

---

## packages/financial_analysis/ingest/adapters/amex_enhanced_details_csv.py

**Purpose**: Adapter for American Express "Enhanced Details" CSVs with preamble; finds real header and maps rows to CTV using the AmEx-like adapter.

**External Interface (exported symbols)**:
- `EXACT_HEADER` (str)
- `REQUIRED_COLUMNS` (set[str])
- `to_ctv_enhanced_details(file: TextIO) -> Iterator[Mapping[str, Any]]`
- `to_ctv_enhanced_details_from_path(path: str) -> Iterable[Mapping[str, Any]]`

**Callers**: 
- `packages/financial_analysis/cli.py`
- `packages/financial_analysis/workflows/review_flow.py`
- Internal adapter module `amex_like_csv` is also a dependency

**Dependencies**: 
- `csv`, `io`
- `collections.abc` (Iterable, Iterator, Mapping)
- `typing` (Any, TextIO)
- `.amex_like_csv.to_ctv` as `_to_ctv_like`

**Data Structures**: 
Produces plain CTV mapping dicts (idx, id, description, amount, date, merchant, memo)

---

## packages/financial_analysis/ingest/adapters/amex_like_csv.py

**Purpose**: Adapter mapping AmEx-like CSV rows (exact header) to CTV mapping dicts with normalization of text and dates.

**External Interface (exported symbols)**:
- `to_ctv(rows: Iterable[Mapping[str, str]]) -> Iterator[Mapping[str, Any]]`
- Helper functions `_clean_text`, `_normalize_date` are module-internal but not underscored in interface terms (still public by Python rules)

**Callers**: 
- `packages/financial_analysis/cli.py`
- `packages/financial_analysis/ingest/adapters/amex_enhanced_details_csv.py`
- `packages/financial_analysis/workflows/review_flow.py`

**Dependencies**: 
- `re`
- `collections.abc` (Iterable, Iterator, Mapping)
- `datetime.datetime`
- `typing.Any`

**Data Structures**: 
Produces plain CTV mapping dicts (idx, id, description, amount, date, merchant, memo)

---

## Dependency Graph Summary

### Public Entrypoints
- `api.identify_refunds`/`partition_transactions`/`report_trends` (stubs)
- `api.review_transaction_categories` (shim to review)
- `workflows.review_flow.review_categories_from_csv`
- `categorize.categorize_expenses`
- CLI commands

### Categorization Core
`categorize` depends on:
- `prompting` (prompts/schema)
- `cache` (compute_dataset_id + page cache using models' PageCache* DTOs)
- `categorization` (input/response validation)
- OpenAI SDK
- `logging_setup`
- `duplicates` + `persistence` for the prefill helper

### Review Flow
`review` depends on:
- `duplicates` (DB lookup + persist)
- `categories` (create/list/validation)
- `persistence` (fingerprint)
- `term_ui` (interactive prompts)
- DB session

### Workflows
`review_flow` composes:
- Ingest adapters
- `categories.load_taxonomy`
- `categorize`
- `persistence.auto_persist_high_confidence`
- `review`

### Models
Central types consumed across: `cache`, `categorize`, `review`, `persistence`, and `api`.

### Normalizers
Independent CSV→CTV pipeline for multiple providers (used separately from CLI/workflow shown here).

### DB Touchpoints
- `categories`
- `duplicates`
- `persistence`
- `review`
- `categorize` (prefill)
- `review_flow` (session)
- `seed_taxonomy` (admin)

**External ORM**: `db.client`, `db.models.finance`

---

## Interface Contracts

### Categorize API
- `categorize_expenses` returns `list[CategorizedTransaction]` in input order
- Requires taxonomy list of dicts with keys at least `code`, `parent_code`
- Validates descriptions present

### Page Cache Schema
- `PageCacheFile` (schema_version=3) with strict alignment checks
- Keyed by (dataset_id, page_size, page_index, settings_hash)

### Review Workflow
- `review_transaction_categories` returns finalized `list[CategorizedTransaction]` (low-confidence remainder in review_flow)
- Persists groups immediately
- Supports creation and rename flows

### Persistence
- Upsert strategy prioritizes (provider, external_id) else fingerprint
- `apply_category_updates` supports `only_unverified` and per-item confidence
- `auto_persist_high_confidence` uses >0.7 threshold

### Duplicates
- `query_group_duplicates` determines unanimous non-null category among matches and returns exemplar rows for display
- `persist_group` enforces allowed sources {"manual","rule"} and batches updates
