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
   ├─ env.py           # Alembic runtime config (reads DATABASE_URL)
   └─ versions/        # Migration scripts live here
```

Notes
- No runtime logic is implemented yet—this is scaffolding only.
- Set `DATABASE_URL` in your environment for Alembic operations; `env.py` injects it at runtime.

## Finance domain schema (public)

The following tables are owned by this library and are created by Alembic migrations:

- `fa_categories`
  - `code text primary key`
  - `display_name text not null unique`
  - `is_active boolean not null default true`
  - `sort_order integer null`
  - `created_at timestamptz not null default now()`
  - `updated_at timestamptz not null default now()`

- `fa_transactions`
  - `id bigint primary key generated always as identity`
  - `source_provider text not null`
  - `source_account text null`
  - `external_id text null`
  - `fingerprint_sha256 char(64) not null unique`
  - `raw_record jsonb not null`
  - `currency_code char(3) not null default 'USD'`
  - `amount numeric(18,2) null`
  - `date date null`
  - `description text null`
  - `merchant text null`
  - `memo text null`
  - `category text null references fa_categories(code) deferrable initially deferred`
  - `category_source text not null default 'unknown'` with `CHECK (category_source in ('llm','manual','rule','import','unknown'))`
  - `category_confidence numeric(3,2) null` with `CHECK (category_confidence >= 0 and category_confidence <= 1)`
  - `categorized_at timestamptz null`
  - `is_deleted boolean not null default false`
  - `created_at timestamptz not null default now()`
  - `updated_at timestamptz not null default now()`

  Indexes and uniques:
  - Partial unique index on `(source_provider, external_id)` where `external_id` is not null (`uniq_fa_tx_provider_external_id`)
  - Unique index on `(fingerprint_sha256)` (`uq_fa_tx_fingerprint`)
  - B-tree index on `(date)` (`ix_fa_transactions_date`)
  - B-tree index on `(category)` (`ix_fa_transactions_category`)
  - B-tree index on `(merchant)` (`ix_fa_transactions_merchant`)

- `fa_refund_pairs`
  - `id bigint primary key generated always as identity`
  - `expense_id bigint not null references fa_transactions(id) on delete cascade`
  - `refund_id bigint not null references fa_transactions(id) on delete cascade`
  - `CHECK (expense_id <> refund_id)`
  - `UNIQUE (expense_id, refund_id)`
  - `created_at timestamptz not null default now()`

Categories are seeded from `financial_analysis.categorization.ALLOWED_CATEGORIES` at migration time.
