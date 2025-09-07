"""Centralized SQLAlchemy engine/session helpers for the workspace.

Usage
-----
from db.client import get_engine, get_session

with get_session() as s:
    s.execute(...)
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_ENGINE: Engine | None = None
_SESSION_MAKER: sessionmaker[Session] | None = None
_DB_URL: str | None = None


def _database_url(override: str | None = None) -> str:
    url = override or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set; cannot initialize database client")
    return url


def get_engine(*, database_url: str | None = None) -> Engine:
    """Return a shared SQLAlchemy engine, creating it on first use."""

    global _ENGINE, _SESSION_MAKER
    url = _database_url(database_url)
    if _ENGINE is None:
        # Default isolation level is fine; echo disabled.
        engine = create_engine(url, pool_pre_ping=True)
        _SESSION_MAKER = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
        _ENGINE = engine
        global _DB_URL
        _DB_URL = url
        return engine
    # Engine already initialized; guard against cross-environment misuse.
    if _DB_URL is not None and url != _DB_URL:
        raise RuntimeError(
            "get_engine() already initialized with a different DATABASE_URL; "
            "restart the process or avoid passing a different URL"
        )
    return _ENGINE


def get_session(*, database_url: str | None = None) -> Session:
    """Return a new SQLAlchemy session bound to the shared engine."""

    get_engine(database_url=database_url)
    assert _SESSION_MAKER is not None  # bound by get_engine
    return _SESSION_MAKER()


@contextmanager
def session_scope(*, database_url: str | None = None) -> Iterator[Session]:
    """Provide a transactional scope around a series of operations."""

    session = get_session(database_url=database_url)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


__all__ = [
    "get_engine",
    "get_session",
    "session_scope",
]
