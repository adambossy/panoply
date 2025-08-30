# db (shared database library)

Scope
- Central place for database access and migrations for the workspace.
- Includes SQLAlchemy, Alembic, and the Supabase Python client.

Layout

```
libs/db/
├─ src/db/
│  ├─ __init__.py
│  ├─ client.py        # Placeholder for engine/session and Supabase helpers
│  └─ models/
│     └─ __init__.py   # Placeholder for shared ORM models or registry
├─ alembic.ini         # Alembic configuration (script_location=alembic)
└─ alembic/
   └─ versions/        # Migration scripts live here
```

Notes
- No runtime logic is implemented yet—this is scaffolding only.
- Point `DATABASE_URL` in your environment for Alembic operations.
