"""Shared SQLAlchemy models registry for the workspace database.

Currently includes finance domain models used by ``financial_analysis``.
"""

from .finance import Base, FaCategory, FaRefundPair, FaTransaction

__all__ = [
    "Base",
    "FaCategory",
    "FaTransaction",
    "FaRefundPair",
]
