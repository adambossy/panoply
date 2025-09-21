# Panoply Monorepo

Workspace scaffolding for a Python 3.12 monorepo managed with uv. It's designed for multiple independent packages (CLIs and/or FastAPI apps) that share a common database library.

## Quickstart

```bash
# 1) Ensure Python 3.12.6 is installed (see .python-version)
# 2) Install uv: https://docs.astral.sh/uv/

# 3) Install all workspace dependencies (root + members)
uv sync

# 4) Copy env template and fill in required values
cp .env.example .env

# 5) Install Git hooks for pre-commit
uv run pre-commit install

# 6) Run repo-wide hooks manually (optional)
uv run pre-commit run --all-files
```

Note: This workspace uses uv-managed execution. Prefer running tools via `uv run <tool>` instead of manually activating a virtualenv; explicit `source .venv/bin/activate` is not required.

## Common tasks

- Run tests: `uv run pytest`
- Lint (Ruff): `uv run ruff check .`
- Type-check: `uv run mypy .`
- Format: `uv run ruff format .`

## Workspace layout

```text
.
├─ packages/           # Application/tool packages (added later)
├─ libs/
│  └─ db/              # Shared DB library (SQLAlchemy/Alembic/Supabase)
├─ docs/
├─ scripts/
├─ pyproject.toml      # uv workspace + dev/test dependency groups
├─ .python-version     # Pinned to Python 3.12.6
├─ .env.example        # Required environment variables (no secrets)
├─ .pre-commit-config.yaml
├─ ruff.toml
├─ mypy.ini
```

## What's included now
- uv workspace configuration targeting Python 3.12
- Baseline tooling: pytest, ruff, mypy, pre-commit (workspace-level dependency groups)
- Shared database library at `libs/db` with placeholders for SQLAlchemy models, Alembic config, and a Supabase/DB client module
- Package scaffolding guide at `packages/README.md`

See [docs/architecture.md](docs/architecture.md) and [docs/contributing.md](docs/contributing.md) for more details.

## Interactive category review (terminal)

The `review-transaction-categories` flow uses a prompt_toolkit completion menu backed by the canonical category list from the database. The predicted category is pre‑filled; press Enter to accept it, or press Tab/arrow keys to open and navigate the dropdown and Enter to confirm a different category.
