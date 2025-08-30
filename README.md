# Panoply Monorepo

Workspace scaffolding for a Python 3.12 monorepo managed with uv. It's designed for multiple independent packages (CLIs and/or FastAPI apps) that share a common database library.

## Quickstart

```bash
# 1) Ensure Python 3.12.x is installed (see .python-version)
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
├─ .python-version     # Python 3.12.x pin (exact patch to confirm)
├─ .env.example        # Required environment variables (no secrets)
├─ .pre-commit-config.yaml
├─ ruff.toml
├─ mypy.ini
└─ LICENSE
```

## What's included now
- uv workspace configuration targeting Python 3.12
- Baseline tooling: pytest, ruff, mypy, pre-commit (workspace-level dependency groups)
- Shared database library at `libs/db` with placeholders for SQLAlchemy models, Alembic config, and a Supabase/DB client module
- Package scaffolding guide at `packages/README.md`

## Open questions
- Python patch version for `.python-version` (pinned here to a 3.12.x placeholder; please confirm exact 3.12.x to use)
- Whether to track a `supabase/` directory in-repo and how it should interact with Alembic migrations in `libs/db`
- Any org-standard secrets management beyond local `.env`

See [docs/architecture.md](docs/architecture.md) and [docs/contributing.md](docs/contributing.md) for more details.
