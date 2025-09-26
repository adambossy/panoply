# ruff: noqa: I001
"""
Alembic configuration for the `db` library.

This file injects the database URL from the `DATABASE_URL` environment variable
at runtime and supports both offline and online migrations. Replace
`target_metadata` with your models' metadata as ORM models are introduced.
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from dotenv import load_dotenv, find_dotenv


def _load_dotenv_candidates() -> None:  # pragma: no cover - side-effectful
    """Best-effort .env loading for Alembic executions.

    Attempts to load a ``.env`` from the current working directory and from the
    repository root (relative to this ``env.py`` file). Failures are ignored so
    that migrations can still proceed when ``python-dotenv`` is unavailable.
    """

    try:
        from dotenv import load_dotenv as _load_dotenv  # local import
    except ImportError:
        return

    try:
        candidates = [
            Path.cwd() / ".env",
            # repo root: libs/db/alembic/env.py → ../../..
            Path(__file__).resolve().parents[3] / ".env",
        ]
    except Exception:
        candidates = [Path.cwd() / ".env"]

    for p in candidates:
        try:
            if p.is_file():
                _load_dotenv(dotenv_path=p, override=False)
        except OSError:
            pass


# Load env before reading DATABASE_URL
_load_dotenv_candidates()

# Alembic Config object, which provides access to the values within
# the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Load environment from a workspace-level .env if present.
#
# Use python-dotenv's `find_dotenv(usecwd=True)` so both invocation styles work:
# - running Alembic from the repo root (CWD=/repo)
# - running inside libs/db (CWD=/repo/libs/db)
# In either case, this will discover `/repo/.env` without requiring the shell
# to preload it.
dotenv_path = find_dotenv(usecwd=True)
if dotenv_path:
    load_dotenv(dotenv_path=dotenv_path, override=False)

# Normalize and validate database URL from environment or INI (env wins).
db_url_maybe = os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
if db_url_maybe is None or db_url_maybe == "":
    raise RuntimeError(
        "DATABASE_URL is not set. Provide it via environment or set "
        "'sqlalchemy.url' in alembic.ini."
    )
# At this point the URL is guaranteed non-empty (and thus non-None for mypy).
db_url: str = db_url_maybe

config.set_main_option("sqlalchemy.url", db_url)
# Also set the option on the INI section so `engine_from_config` sees it.
config.set_section_option(config.config_ini_section, "sqlalchemy.url", db_url)

# Import target metadata from the shared db package so Alembic can autogenerate
# based on ORM models. This requires libs/db/src to be importable (uv workspace
# handles that for local runs).
logger = logging.getLogger("alembic.env")

try:  # pragma: no cover - import side effects only
    import db as _db_pkg

    target_metadata = getattr(_db_pkg, "metadata", None)
except Exception as exc:  # pragma: no cover - defensive fallback
    # As a defensive fallback, keep target_metadata=None so Alembic can still
    # run purely SQL migrations. This shouldn't happen in normal operation.
    logger.warning(
        "Could not import db.metadata for autogenerate; falling back to None. "
        "Autogenerate may be incomplete. Error: %s",
        exc,
    )
    target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = db_url
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
