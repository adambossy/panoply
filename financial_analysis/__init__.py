"""Public interface for the ``financial_analysis`` package.

This module exposes the package's API functions and public models/types as the
stable import surface. There is no runtime logic here—only symbol re-exports.

Note: This package currently defines interfaces and CLI stubs only. All
callables raise ``NotImplementedError`` by design; implementation details are
intentionally out of scope for this iteration.
"""

from .api import (
    categorize_expenses,
    identify_refunds,
    partition_transactions,
    report_trends,
    review_transaction_categories,
)
from .models import (
    CategorizedTransaction,
    PartitionPeriod,
    RefundMatch,
    TransactionPartitions,
    TransactionRecord,
    Transactions,
)

__all__ = [
    # API
    "categorize_expenses",
    "identify_refunds",
    "partition_transactions",
    "report_trends",
    "review_transaction_categories",
    # Models / types
    "TransactionRecord",
    "CategorizedTransaction",
    "RefundMatch",
    "PartitionPeriod",
    "Transactions",
    "TransactionPartitions",
]
