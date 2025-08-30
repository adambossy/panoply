# Architecture overview

Monorepo managed by uv workspaces, targeting Python 3.12. The repository is organized into independent application/tool packages and shared libraries, with a single lockfile for reproducible environments.

High-level layout

```
.
├─ packages/           # App/tool packages (Typer CLIs; some may expose FastAPI apps)
├─ libs/
│  └─ db/              # Shared database library (SQLAlchemy/Alembic/Supabase)
└─ docs/ | scripts/    # Documentation and helper scripts
```

Dependency direction
- packages/* → may depend on libs/db
- libs/* → must not depend on packages/*

Database ownership
- `libs/db` owns the SQLAlchemy engine/session setup (to be implemented later), common ORM models, and Alembic migrations under `libs/db/alembic/`.
- Application packages import from `db` rather than creating their own engines or migrations.
