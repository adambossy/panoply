"""DB helpers for tests: bootstrap a temporary SQLite DB and seed taxonomy."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from db import Base
from db.client import get_engine, session_scope
from db.models.finance import FaCategory
from sqlalchemy import event
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session


def bootstrap_sqlite_db(db_file: Path) -> str:
    """Create a SQLite database file, initialize schema, and return the URL.

    Using a file-backed SQLite DB ensures multiple SQLAlchemy connections share
    the same state (in-memory DBs are per-connection by default).
    """

    url = f"sqlite+pysqlite:///{db_file}"
    # Ensure parent exists before engine creation attempts any writes
    db_file.parent.mkdir(parents=True, exist_ok=True)
    engine = get_engine(database_url=url)

    # Define a SQLite-compatible `now()` SQL function so server_default=now() works
    @event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _):  # pragma: no cover - tiny bridge
        try:
            from datetime import datetime

            dbapi_conn.create_function(
                "now", 0, lambda: datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            )
        except Exception:
            # Best-effort; tests will fail loudly if this isn't working
            pass
    Base.metadata.create_all(bind=engine)
    # Create the partial unique index used by upserts on (provider, external_id)
    with session_scope(database_url=url) as session:
        # SQLite-friendly replacement for `fa_transactions.id BIGINT PRIMARY KEY` so
        # inserts can auto-generate rowids. SQLite requires `INTEGER PRIMARY KEY`.
        session.execute(sql_text("DROP TABLE IF EXISTS fa_transactions"))
        session.execute(
            sql_text(
                """
                CREATE TABLE fa_transactions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  source_provider TEXT NOT NULL,
                  source_account TEXT NULL,
                  external_id TEXT NULL,
                  fingerprint_sha256 CHAR(64) NOT NULL UNIQUE,
                  raw_record JSON NOT NULL,
                  currency_code CHAR(3) NOT NULL DEFAULT 'USD',
                  amount NUMERIC NULL,
                  date DATE NULL,
                  description TEXT NULL,
                  merchant TEXT NULL,
                  memo TEXT NULL,
                  display_name TEXT NULL,
                  display_name_source TEXT NOT NULL DEFAULT 'unknown',
                  renamed_at DATETIME NULL,
                  verified BOOLEAN NOT NULL DEFAULT 0,
                  category TEXT NULL,
                  category_source TEXT NOT NULL DEFAULT 'unknown',
                  category_confidence NUMERIC NULL,
                  categorized_at DATETIME NULL,
                  is_deleted BOOLEAN NOT NULL DEFAULT 0,
                  created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                  updated_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                  FOREIGN KEY(category) REFERENCES fa_categories(code)
                )
                """
            )
        )
        session.execute(
            # SQLite supports partial indexes with a WHERE clause (>=3.8)
            # This mirrors the Postgres migration 0001 index.
            # nosec - test-only DDL
            sql_text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uniq_fa_tx_provider_external_id\n"
                "ON fa_transactions (source_provider, external_id)\n"
                "WHERE external_id IS NOT NULL"
            )
        )
        session.flush()
    # Make it the default for any code paths that read from the environment
    os.environ.setdefault("DATABASE_URL", url)
    return url


def seed_full_taxonomy_from_json(*, database_url: str, json_path: Path) -> None:
    """Insert the two-level taxonomy JSON (parents first, then children)."""

    data: list[dict[str, Any]]
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    with session_scope(database_url=database_url) as session:
        _clear_categories(session)
        _insert_taxonomy(session, data)


def _clear_categories(session: Session) -> None:
    # Portable clear for SQLite without TRUNCATE
    session.query(FaCategory).delete()
    session.flush()


def _insert_taxonomy(session: Session, data: list[dict[str, Any]]) -> None:
    # Insert parents first to satisfy FK on children
    order = 0
    now = datetime.now(datetime.UTC)
    for parent in data:
        code = str(parent.get("code") or parent.get("display_name"))
        name = str(parent.get("display_name") or code)
        session.add(
            FaCategory(
                code=code,
                display_name=name,
                parent_code=None,
                is_active=True,
                sort_order=order,
                created_at=now,
                updated_at=now,
            )
        )
        order += 1
    session.flush()

    # Children under each parent (preserve relative order with sort_order)
    for parent_index, parent in enumerate(data):
        pcode = parent.get("code")
        for child_index, child in enumerate(parent.get("children") or []):
            ccode = str(child.get("code") or child.get("display_name"))
            cname = str(child.get("display_name") or ccode)
            session.add(
                FaCategory(
                    code=ccode,
                    display_name=cname,
                    parent_code=pcode,
                    is_active=True,
                    sort_order=(parent_index * 100 + child_index),
                    created_at=now,
                    updated_at=now,
                )
            )
    session.flush()
