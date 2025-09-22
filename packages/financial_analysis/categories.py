"""Category domain helpers and service operations.

This module centralizes small, server-side validated operations for the
``fa_categories`` reference table and exposes a minimal API used by the review
flow. Validation is duplicated lightly on the client (terminal UI) but is
authoritatively enforced here.

Exports
-------
- ``createCategory(...)``: idempotent category creation with case-insensitive
  conflict detection. Returns the created/existing row and a ``created`` flag.
- ``normalize_name(...)`` and ``validate_name(...)``: helper utilities shared
  by the terminal UI to provide early feedback before hitting the database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TypedDict

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# ---------------------------
# Name normalization/validation
# ---------------------------

_ALLOWED_RE = re.compile(r"^[A-Za-z0-9 &\-/]+$")


def normalize_name(name: str) -> str:
    """Return a trimmed, single-spaced representation of ``name``.

    Does not change case; consumers may choose preferred casing conventions.
    """

    # Trim and collapse internal whitespace to single spaces
    s = " ".join(name.strip().split())
    return s


@dataclass(frozen=True, slots=True)
class NameValidation:
    ok: bool
    reason: str | None = None


def validate_name(name: str, *, min_len: int = 1, max_len: int = 64) -> NameValidation:
    """Lightweight client/server validation for category names.

    Rules
    -----
    - Trim whitespace; enforce length bounds 1..64.
    - Allowed characters: letters, numbers, spaces, and ``& - /``.
    """

    n = normalize_name(name)
    if len(n) < min_len:
        return NameValidation(False, "Name cannot be empty")
    if len(n) > max_len:
        return NameValidation(False, f"Name must be at most {max_len} characters")
    if not _ALLOWED_RE.match(n):
        return NameValidation(False, "Only letters, numbers, spaces, and & - / are allowed")
    return NameValidation(True, None)


# ---------------------------
# Service result shape
# ---------------------------


class CategoryDict(TypedDict):
    code: str
    display_name: str
    is_active: bool
    sort_order: int | None


class CreateCategoryResult(TypedDict):
    category: CategoryDict
    created: bool


def _row_to_dict(row) -> CategoryDict:  # pragma: no cover - trivial mapping
    return {
        "code": row.code,
        "display_name": row.display_name,
        "is_active": bool(row.is_active),
        "sort_order": row.sort_order,
    }


def createCategory(
    session: Session,
    *,
    code: str,
    display_name: str | None = None,
    sort_order: int | None = None,
) -> CreateCategoryResult:
    """Create a new category if it doesn't exist (case-insensitive).

    Parameters
    ----------
    session:
        SQLAlchemy session to use (callers own the transaction scope).
    code:
        Primary identifier for the category. The review flow uses the entered
        ``Name`` as the ``code``.
    display_name:
        Optional display label. Defaults to ``code`` when omitted/empty.
    sort_order:
        Optional integer sort hint. ``None`` indicates default alphabetical
        behavior.

    Returns
    -------
    dict
        A mapping ``{"category": { ... }, "created": bool}``.

    Idempotency
    -----------
    Treats case-insensitive duplicates of ``code`` or ``display_name`` as
    conflicts and returns the existing row with ``created=False``.
    """

    # Attempt creation after normalization/validation

    code_n = normalize_name(code)
    dn_raw = display_name if (display_name and display_name.strip()) else code_n
    display_n = normalize_name(dn_raw)

    # Authoritative server-side validation
    v_code = validate_name(code_n)
    v_disp = validate_name(display_n)
    if not v_code.ok:
        reason = v_code.reason or "invalid_code"
        raise ValueError(f"Invalid category code: {reason}")
    if not v_disp.ok:
        reason = v_disp.reason or "invalid_display_name"
        raise ValueError(f"Invalid display name: {reason}")

    # Case-insensitive existence check across code OR display_name
    from db.models.finance import FaCategory  # local import

    existing = (
        session.execute(
            select(FaCategory).where(
                (func.lower(FaCategory.code) == code_n.lower())
                | (func.lower(FaCategory.display_name) == display_n.lower())
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        return {"category": _row_to_dict(existing), "created": False}

    # Insert row; rely on DB defaults for timestamps and is_active default=true
    row = FaCategory(
        code=code_n,
        display_name=display_n,
        is_active=True,
        sort_order=sort_order,
    )
    try:
        session.add(row)
        session.flush()  # obtain DB-computed defaults if any
    except IntegrityError:  # pragma: no cover - depends on DB uniqueness
        session.rollback()
        # Race or case-variance conflict; fetch existing and return no-op
        from db.models.finance import FaCategory  # local import

        existing = (
            session.execute(
                select(FaCategory).where(
                    (func.lower(FaCategory.code) == code_n.lower())
                    | (func.lower(FaCategory.display_name) == display_n.lower())
                )
            )
            .scalars()
            .first()
        )
        if existing is None:
            raise
        return {"category": _row_to_dict(existing), "created": False}
    except Exception:  # pragma: no cover - defensive
        session.rollback()
        raise

    return {"category": _row_to_dict(row), "created": True}


# PEP8-friendly alias (optional)
create_category = createCategory

__all__ = [
    "normalize_name",
    "validate_name",
    "createCategory",
    "create_category",
    "NameValidation",
    "CategoryDict",
    "CreateCategoryResult",
]
