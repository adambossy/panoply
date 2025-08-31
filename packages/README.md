This directory holds application/tool packages.

Expected per-package structure

```
packages/<package-name>/
├─ pyproject.toml                 # PEP 621 metadata; Typer CLI under [project.scripts]
├─ README.md
├─ src/
│  └─ <package_name>/
│     ├─ __init__.py
│     ├─ cli.py                   # Typer entry point placeholder when created
│     └─ api/
│        └─ main.py               # FastAPI app placeholder when created
└─ tests/
   ├─ unit/
   └─ integration/
```

Notes
- Target Python 3.12: set `requires-python = ">=3.12,<3.13"` in each package.
- Add only the runtime deps a package needs (e.g., `fastapi`, `uvicorn[standard]`, `openai`).
- Depend on the shared DB library with `db` in `[project.dependencies]` when needed.
- Declare a CLI command in `[project.scripts]`, pointing to a Typer `app` in `src/<package_name>/cli.py`.
