"""db: shared database library (SQLAlchemy/Alembic/Supabase).

Public exports
--------------
- ``Base`` and ``metadata`` for Alembic autogenerate/targeting
- ORM models in ``db.models.finance`` (re-exported for convenience)
- Engine/session helpers in ``db.client``
"""

from __future__ import annotations

from .models.finance import Base, FaCategory, FaTransaction

# Re-export SQLAlchemy metadata for Alembic's env.py
metadata = Base.metadata

__all__ = [
    "Base",
    "metadata",
    "FaCategory",
    "FaTransaction",
]
