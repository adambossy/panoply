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

## Database schema (finance domain)

Created via Alembic migrations in `libs/db/alembic/versions`:

- `fa_categories(code, display_name, is_active, sort_order, created_at, updated_at)`
- `fa_transactions(id, source_provider, source_account, external_id, fingerprint_sha256, raw_record, currency_code, amount, date, description, merchant, memo, category, category_source, category_confidence, categorized_at, is_deleted, created_at, updated_at)`
  - Partial unique index: `(source_provider, external_id)` where `external_id` is not null (`uniq_fa_tx_provider_external_id`)
  - Unique index: `(fingerprint_sha256)` (`uq_fa_tx_fingerprint`)
  - Indexes: `(date)`, `(category)`, `(merchant)`
- `fa_refund_pairs(id, expense_id→fa_transactions.id, refund_id→fa_transactions.id, created_at)` with `CHECK (expense_id <> refund_id)` and `UNIQUE (expense_id, refund_id)`

`fa_categories` is seeded from `financial_analysis.categorization.ALLOWED_CATEGORIES` at migration time.
