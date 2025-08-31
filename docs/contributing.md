# Contributing

Prerequisites
- Python 3.12.6 (see `.python-version` for the exact patch to use)
- [uv](https://docs.astral.sh/uv/) installed

Setup

```bash
uv sync
uv run pre-commit install
```

Adding a new package
1. Create a directory at `packages/<dist-name>/`.
2. Use src layout: `src/<package_name>/` (snake_case for the Python package; kebab-case for the distribution name and CLI command).
3. Add `pyproject.toml` with PEP 621 metadata:
   - `requires-python = ">=3.12,<3.13"`
   - `[project.scripts]` to expose a Typer CLI (e.g., `<cmd> = "<package_name>.cli:app"`).
   - Add runtime deps as needed (e.g., `fastapi`, `uvicorn[standard]`, `openai`).
4. If the package needs database access, add `db` to `[project.dependencies]` and import from `db`.
5. Add tests under `tests/` (e.g., `tests/unit/`, `tests/integration/`).

Depending on shared libraries
- Use workspace dependencies: list `db` in the member’s `[project.dependencies]`. uv will resolve it from `libs/db` inside the workspace.

Common commands

```bash
# Run a package CLI from anywhere
uv run --package <dist-name> <cli-name> --help

# Run a package’s FastAPI app
uv run --package <dist-name> uvicorn <package_name>.api.main:app --reload --port 8000

# Run tests for one member
uv run --package <dist-name> pytest -q

# Lint / type-check everything via pre-commit
uv run pre-commit run --all-files
```

Coding standards
- Ruff and mypy configs live at the repo root and apply to all members.
- Prefer Pydantic for request/response DTOs and internal schemas.

Secrets & environment
- Do not commit secrets. Copy `.env.example` to `.env` for local development.
