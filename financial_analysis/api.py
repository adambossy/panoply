"""Public API interfaces for the ``financial_analysis`` package.

All functions in this module are interface definitions only. Bodies raise
``NotImplementedError`` by design; no business logic is provided in this
iteration. Inputs/outputs are documented exactly as requested, along with
explicit notes on ambiguities that require clarification.
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import (
    CategorizedTransaction,
    RefundMatch,
    TransactionPartitions,
    Transactions,
)


def categorize_expenses(csv_path: str) -> Iterable[CategorizedTransaction]:
    """Categorize transactions from a bank-exported CSV using an LLM (interface only).

    Input
    -----
    csv_path:
        Path to a CSV file containing bank-exported transactions.

    Output
    ------
    An iterable of transactions, each paired with a category (see
    :class:`~financial_analysis.models.CategorizedTransaction`).

    Notes
    -----
    - The eventual implementation will use a Large Language Model (LLM) to
      assign categories; however, this API only defines the interface and does
      not expose model configuration or parameters at this time.
    - CSV schema is unspecified: required column names and types (e.g., date,
      amount, description, unique identifiers) need to be confirmed before any
      implementation.
    - Category ontology and normalization rules (e.g., allowed labels, casing,
      hierarchy) are not defined and require clarification.
    """

    raise NotImplementedError


def identify_refunds(csv_path: str) -> Iterable[RefundMatch]:
    """Identify expense/refund pairs from a CSV by inverse dollar amounts (interface only).

    Input
    -----
    csv_path:
        Path to a CSV file containing transactions.

    Output
    ------
    An iterable of pairs of row indices, each tuple identifying the expense row
    and the corresponding refund row in the original CSV (see
    :class:`~financial_analysis.models.RefundMatch`).

    Notes
    -----
    - Row indexing convention (0-based vs 1-based) is not specified and MUST
      be clarified. This API does not commit to one or the other.
    - The amount column name and format are unspecified (e.g., whether refunds
      are negative amounts, sign conventions, currency/rounding).
    - CSV schema for dates and any time-based disambiguation is not defined.
    """

    raise NotImplementedError


def partition_transactions(
    transactions: Transactions, partition_period: object
) -> TransactionPartitions:
    """Partition a transaction collection into subsets over a period (interface only).

    Input
    -----
    transactions:
        A collection of transaction records.
    partition_period:
        A period specifier used to partition the transactions. The format for
        this value is not defined here and requires clarification (e.g., string
        values such as "monthly"/"quarterly" vs a date duration object or
        other spec). Timezone and calendar assumptions are also unspecified.

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
) -> Iterable[CategorizedTransaction]:
    """Review and correct transaction categories via a REPL-style flow (interface only).

    Input
    -----
    transactions_with_categories:
        An iterable of transactions that already have categories assigned.

    Output
    ------
    An iterable of transactions with verified or corrected categories following
    a REPL-style review process (see
    :class:`~financial_analysis.models.CategorizedTransaction`).

    Notes
    -----
    - REPL interaction details (prompts, commands, confirmation flow) are not
      specified and require clarification.
    - The category ontology and normalization rules are not defined.
    - CSV schema (required column names and formats) remains unspecified.
    """

    raise NotImplementedError
