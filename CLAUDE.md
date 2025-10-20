# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Panoply is a Python 3.12 monorepo for financial transaction analysis and categorization, managed by uv workspaces. It includes a CLI tool for expense categorization with LLM-powered predictions and an interactive terminal UI for review.

## Development Setup

```bash
# Install workspace dependencies
uv sync

# Install pre-commit hooks
uv run pre-commit install

# Copy environment template and configure
cp .env.example .env
# Required: DATABASE_URL, OPENAI_API_KEY
```

## Common Commands

### Testing
```bash
# Run all tests
uv run pytest

# Run tests for a specific package
uv run --package financial_analysis pytest -q

# Run a single test file
uv run pytest tests/test_api_categorize_expenses.py
```

### Linting & Type Checking
```bash
# Lint with Ruff
uv run ruff check .

# Auto-fix lint issues
uv run ruff check --fix .

# Format code
uv run ruff format .

# Type check
uv run mypy .

# Run all pre-commit hooks manually
uv run pre-commit run --all-files
```

### Database Migrations
```bash
# Apply migrations (from repo root)
uv run alembic -c libs/db/alembic.ini upgrade head

# Check current migration status
uv run alembic -c libs/db/alembic.ini current

# View migration history
uv run alembic -c libs/db/alembic.ini history --indicate-current

# Create a new migration (use zero-padded rev_id)
uv run alembic -c libs/db/alembic.ini revision -m "Description" --rev-id 00XX
```

### Running the CLI
```bash
# Run the financial analysis CLI
uv run --package financial_analysis fa --help

# Example: categorize transactions
uv run --package financial_analysis fa categorize-expenses \
  --csv-path data/input.csv \
  --source-provider chase

# Example: interactive review
uv run --package financial_analysis fa review-transaction-categories \
  --csv-path data/input.csv \
  --source-provider amex
```

## Architecture

### Workspace Structure
```
packages/financial_analysis/    # Main CLI application (Typer-based)
libs/db/                        # Shared database library (SQLAlchemy/Alembic)
libs/pmap/                      # Parallel mapping utility (currently empty stub)
```

### Dependency Direction
- `packages/*` may depend on `libs/*`
- `libs/*` must NOT depend on `packages/*`

### Key Components

**Database Layer (`libs/db`)**
- SQLAlchemy engine/session management in `db.client`
- ORM models in `db.models.finance` (FaCategory, FaTransaction)
- Alembic migrations in `libs/db/alembic/versions/`
- Schema: `fa_categories` (taxonomy), `fa_transactions` (core transaction table)

**Financial Analysis Package (`packages/financial_analysis`)**
- CLI entry point: `cli.py` (Typer app)
- Categorization logic: `categorize.py`, `categorization.py`, `prompting.py`
- Interactive terminal UI: `term_ui.py`, `review.py` (prompt_toolkit-based)
- CSV normalizers: `normalizers.py` (provider-specific to CTV transformation)
- Persistence: `persistence.py` (transaction upserts)

**Canonical Transaction View (CTV)**
- Normalized schema for all providers: `{idx, id, description, amount, date, merchant, category, memo}`
- Model: `ctv.py::CanonicalTransaction`
- Provider adapters in `normalizers.py` for AMEX, Chase, Alliant, Morgan Stanley, Amazon, Venmo

### Database Taxonomy
- `fa_categories` is the sole source of truth for the expense taxonomy
- Do NOT maintain hardcoded category lists in application code
- Categories are hierarchical (two-level: parent categories with optional subcategories)
- Parent-child relationships via `parent_code` FK; uniqueness enforced on `(coalesce(parent_code,'__root__'), lower(display_name))`

### LLM Categorization Flow
1. Load taxonomy from `fa_categories` table
2. Batch transactions into chunks (configurable chunk size, default 100)
3. Parallel processing via ThreadPoolExecutor (concurrency=4)
4. Cache results in `.transactions/` directory (keyed by dataset_id hash of input + settings)
5. Interactive review via prompt_toolkit completion menu

## Important Conventions

### Code Style
- Python 3.12 (see `.python-version`)
- Ruff for linting and formatting (config: `ruff.toml`)
- Type hints preferred but not strictly enforced (mypy config: `mypy.ini`)
- Use Pydantic for DTOs and schemas

### Package Management
- Use `uv run <tool>` instead of manually activating virtualenv
- For package-specific commands: `uv run --package <dist-name> <command>`
- Workspace dependencies resolved via `[tool.uv.sources]` in `pyproject.toml`

### Migration Workflow
- Use zero-padded numeric revision IDs (e.g., `0001`, `0002`) instead of Alembic's random hashes
- Alembic reads `DATABASE_URL` from repo-root `.env` (auto-loaded by `env.py`)
- Always run migrations from repo root with `-c libs/db/alembic.ini` flag

### Testing
- Tests live at repo root: `tests/`
- Snapshot testing used for normalizers (`tests/test_normalizers_snapshots.py`)
- Integration tests for categorization API

### Environment Variables
- `DATABASE_URL` (required): PostgreSQL connection string (psycopg driver)
- `OPENAI_API_KEY` (required): OpenAI API key for LLM categorization
- `LOG_LEVEL` (optional): DEBUG | INFO | WARNING | ERROR | CRITICAL

## Adding a New Package

1. Create directory: `packages/<dist-name>/`
2. Use src layout: `src/<package_name>/` (snake_case for Python package, kebab-case for dist name)
3. Add `pyproject.toml` with PEP 621 metadata:
   - `requires-python = ">=3.12,<3.13"`
   - `[project.scripts]` for CLI entry points
   - Add `db` to dependencies if database access needed
4. Register in workspace: add to `[tool.uv.workspace] members` in root `pyproject.toml`

## Common Patterns

### Database Session Usage
```python
from db.client import session_scope

with session_scope() as session:
    result = session.execute(select(FaCategory).where(...))
    session.commit()  # Automatic on context exit
```

### Parallel Processing
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

with ThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(process_item, item) for item in items]
    results = [f.result() for f in as_completed(futures)]
```

### CSV Normalization
- All provider-specific normalizers inherit from `CSVNormalizer`
- Output must conform to CTV schema (see `docs/financial_analysis_ctv.md`)
- Use `to_ctv_record()` method to produce normalized output

## Interactive Review Flow

The `review-transaction-categories` command provides an interactive terminal UI:
- Pre-filled with predicted category (press Enter to accept)
- Press Down (↓) to open dropdown menu showing all categories
- Type prefix to filter categories; Tab to autocomplete
- Ghost text shows inline suggestions for matching prefixes
- Requires database access to load categories and persist choices
