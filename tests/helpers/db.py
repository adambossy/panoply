"""DB helpers for tests: bootstrap a temporary SQLite DB and seed taxonomy."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from db import Base
from db.client import get_engine, session_scope
from db.models.finance import FaCategory, FaTransaction
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    event,
)
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session
from sqlalchemy.schema import MetaData, Table


def bootstrap_sqlite_db(db_file: Path, *, set_default_env: bool = False) -> str:
    """Create a SQLite database file, initialize schema, and return the URL.

    Using a file-backed SQLite DB ensures multiple SQLAlchemy connections share
    the same state (in-memory DBs are per-connection by default).
    """

    url = f"sqlite+pysqlite:///{db_file}"
    # Ensure parent exists before engine creation attempts any writes
    db_file.parent.mkdir(parents=True, exist_ok=True)
    engine = get_engine(database_url=url)

    # Enforce FKs and provide a `now()` shim so server_default=now() works
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _):  # pragma: no cover - tiny bridge
        try:
            dbapi_conn.execute("PRAGMA foreign_keys = ON")
            from datetime import UTC, datetime
            dbapi_conn.create_function(
                "now", 0, lambda: datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
            )
        except Exception:
            # Best effort; any mismatch will surface in tests
            pass

    # Only create taxonomy tables from metadata; we'll create transactions below
    Base.metadata.create_all(bind=engine, tables=[FaCategory.__table__])

    # Build transactions table dynamically from ORM to avoid drift
    _create_sqlite_fa_transactions(engine)
    _assert_transactions_schema_in_sync(url)

    # Make it the default for any code paths that read from the environment
    if set_default_env:
        # Preserve prior non-overriding semantics
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
    """Clear taxonomy rows in FK-safe order (children first, then parents)."""
    # Delete children first to satisfy self-referential FK
    session.query(FaCategory).filter(FaCategory.parent_code.isnot(None)).delete(
        synchronize_session=False
    )
    session.query(FaCategory).filter(FaCategory.parent_code.is_(None)).delete(
        synchronize_session=False
    )
    session.flush()


def _insert_taxonomy(session: Session, data: list[dict[str, Any]]) -> None:
    # Insert parents first to satisfy FK on children
    order = 0
    now = datetime.now(UTC)
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


def _create_sqlite_fa_transactions(engine) -> None:
    """Create the `fa_transactions` table in SQLite based on the ORM model.

    Differences from Postgres:
    - `id` is `INTEGER PRIMARY KEY` (rowid) instead of `BIGINT` to enable
      implicit autoincrement behavior in SQLite.
    - The partial unique index on `(source_provider, external_id)` is created
      separately with a `WHERE external_id IS NOT NULL` predicate (mirrors
      migration 0001).
    """

    meta = MetaData()
    # Ensure the referenced table exists in the same MetaData for FK resolution
    Table(FaCategory.__tablename__, meta, autoload_with=engine)

    cols: list[Column] = []
    for c in FaTransaction.__table__.columns:
        # Rebuild FK relationships (Column.copy() drops FKs and is deprecated)
        fks = []
        if c.foreign_keys:
            for fk in c.foreign_keys:
                # Keep it simple; SQLite ignores deferrable semantics anyway
                fks.append(ForeignKey(str(fk.target_fullname)))

        # Translate the ID column for SQLite rowid semantics
        if c.name == "id":
            new_col = Column(
                "id",
                Integer,
                primary_key=True,
                autoincrement=True,
                nullable=False,
            )
        else:
            new_col = Column(
                c.name,
                c.type,
                *fks,
                primary_key=c.primary_key,
                nullable=c.nullable,
                unique=c.unique,
                server_default=(c.server_default.arg if c.server_default is not None else None),
            )

        cols.append(new_col)

    # Carry over table-level CHECK constraints
    checks: list[CheckConstraint] = []
    for cons in FaTransaction.__table__.constraints:
        if isinstance(cons, CheckConstraint):
            checks.append(CheckConstraint(cons.sqltext, name=cons.name))

    tx = Table(
        "fa_transactions",
        meta,
        *cols,
        *checks,
        sqlite_autoincrement=True,  # emit AUTOINCREMENT keyword for rowid PK
    )

    # Create table and the partial unique index used by upserts
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS fa_transactions")
        tx.create(bind=conn)
        conn.exec_driver_sql(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uniq_fa_tx_provider_external_id
            ON fa_transactions (source_provider, external_id)
            WHERE external_id IS NOT NULL
            """
        )


def _assert_transactions_schema_in_sync(database_url: str) -> None:
    """Quick sanity check: ORM column set matches SQLite table column set.

    This catches accidental divergence if the model changes and the helper is
    not updated accordingly.
    """
    expected = {c.name for c in FaTransaction.__table__.columns}
    with session_scope(database_url=database_url) as session:
        rows = session.execute(sql_text("PRAGMA table_info('fa_transactions')")).fetchall()
        got = {row[1] for row in rows}  # (cid, name, type, notnull, dflt_value, pk)
    missing = expected - got
    extra = got - expected
    assert not missing and not extra, (
        f"fa_transactions schema drift: missing={missing or '∅'}, extra={extra or '∅'}"
    )
