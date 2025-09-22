"""Public API interfaces and orchestration for the ``financial_analysis`` package.

This module primarily serves as a stable import surface. The concrete
implementation of :func:`categorize_expenses` lives in
``financial_analysis.categorize`` and is re-exported here. The
``review_transaction_categories`` implementation now lives in
``financial_analysis.review`` and is re-exported here for compatibility. Other
interfaces remain stubs and raise ``NotImplementedError`` by design.
"""

from __future__ import annotations

from collections.abc import Iterable

# Compatibility aliases and re-exports
from openai import OpenAI as OpenAI  # re-export for monkeypatch compatibility

from .categorize import categorize_expenses  # noqa: F401  (re-export)
from .models import (
    CategorizedTransaction,
    PartitionPeriod,
    RefundMatch,
    TransactionPartitions,
    Transactions,
)

# DB and persistence imports are intentionally local within functions to keep
# import-time costs low for consumers that don't use the DB-backed review flow.


def identify_refunds(transactions: Transactions) -> Iterable[RefundMatch]:
    """Identify expense/refund pairs by inverse amounts (interface only).

    Input
    -----
    transactions:
        A collection of :data:`~financial_analysis.models.TransactionRecord`
        items to search for refund relationships.

    Output
    ------
    An iterable of expense/refund pairs as
    :class:`~financial_analysis.models.RefundMatch`, where each element holds
    the full :data:`TransactionRecord` for the expense and its matching
    refund.

    Notes
    -----
    - The amount column name and format are unspecified (e.g., whether refunds
      are negative amounts, sign conventions, currency/rounding).
    - Date schema and any time-based disambiguation rules are not defined.
    """

    raise NotImplementedError


def partition_transactions(
    transactions: Transactions, partition_period: PartitionPeriod
) -> TransactionPartitions:
    """Partition a transaction collection into period-based subsets (interface only).

    Input
    -----
    transactions:
        A collection of transaction records.
    partition_period:
        A structured period spec (see
        :class:`~financial_analysis.models.PartitionPeriod`) that supports any
        combination of ``years``, ``months``, ``weeks``, and ``days``. Each
        field is optional and the fields are not mutually exclusive.

    Output
    ------
    An iterable of partitions, where each partition is a subset of the input
    transactions (see :data:`~financial_analysis.models.TransactionPartitions`).

    Notes
    -----
    - The required date column name and its format are not specified and must
      be clarified for any implementation.
    - The ordering of transactions within and across partitions is unspecified.
    """

    raise NotImplementedError


def report_trends(transactions: Transactions) -> str:
    """Produce a pretty-printed trends table by category by month (interface only).

    Input
    -----
    transactions:
        A collection of transaction records.

    Output
    ------
    A string containing a pretty-printed table showing spending totals by
    category by month and overall totals. Rendering/printing of this string is
    the caller's responsibility; this API returns the string only.

    Notes
    -----
    - Required column names and formats (e.g., date, amount, category) are not
      specified and require clarification.
    - Timezone/calendar assumptions and how months are defined (posting vs
      transaction date) are unspecified.
    - Category normalization rules and aggregation semantics are not defined.
    """

    raise NotImplementedError


def review_transaction_categories(
    transactions_with_categories: Iterable[CategorizedTransaction],
    *,
    source_provider: str,
    source_account: str | None,
    database_url: str | None = None,
    exemplars: int = 5,
    select_category_fn=None,
    allow_create: bool | None = None,
) -> list[CategorizedTransaction]:
    """Compatibility shim that delegates to ``financial_analysis.review``.

    Defined here to keep the public import path stable while ensuring the heavy
    DB-related imports in ``financial_analysis.review`` are only loaded when this
    function is actually used.
    """

    from .review import review_transaction_categories as _impl

    return _impl(
        transactions_with_categories,
        source_provider=source_provider,
        source_account=source_account,
        database_url=database_url,
        exemplars=exemplars,
        selector=select_category_fn,
        allow_create=allow_create,
    )
