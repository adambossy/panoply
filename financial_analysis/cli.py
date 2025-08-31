"""CLI stubs for the ``financial_analysis`` package.

This module intentionally does not depend on any specific argument-parsing
library. It defines function signatures and docstrings that mirror the public
API. All callables raise ``NotImplementedError``; printing behavior, file I/O,
and argument parsing are out of scope for this iteration and require
clarification.
"""

from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``financial_analysis`` CLI (stub).

    Parameters
    ----------
    argv:
        Command-line arguments, excluding the program name. When ``None``, the
        eventual implementation would read from ``sys.argv[1:]``.

    Returns
    -------
    int
        Process exit code. ``0`` indicates success. The actual parsing and
        dispatch to subcommands is not implemented here.

    Subcommands
    -----------
    The CLI is expected to expose one subcommand per public API function:

    - ``categorize-expenses <csv_path>``
    - ``identify-refunds <csv_path>``
    - ``partition-transactions <csv_path> <partition_period>``
    - ``report-trends <csv_path>``
    - ``review-transaction-categories <csv_path_with_categories>``

    Notes
    -----
    - Output formats and destinations are not specified: whether results should
      be printed to stdout, written to files, and in which format (CSV/JSON/
      table) requires clarification.
    - No argument-parsing library is chosen at this time.
    """

    raise NotImplementedError


def cmd_categorize_expenses(csv_path: str) -> int:
    """CLI handler for ``categorize-expenses <csv_path>`` (stub).

    Parameters
    ----------
    csv_path:
        Path to a CSV file containing bank-exported transactions.

    Returns
    -------
    int
        Process exit code. The function is a stub and does not perform I/O.

    Notes
    -----
    - Mirrors the :func:`financial_analysis.api.categorize_expenses` API.
    - Output format for CLI execution (printing vs files; CSV vs JSON) is not
      specified and requires clarification.
    """

    raise NotImplementedError


def cmd_identify_refunds(csv_path: str) -> int:
    """CLI handler for ``identify-refunds <csv_path>`` (stub).

    Parameters
    ----------
    csv_path:
        Path to a CSV file containing transactions.

    Returns
    -------
    int
        Process exit code. The function is a stub and does not perform I/O.

    Notes
    -----
    - Mirrors the :func:`financial_analysis.api.identify_refunds` API.
    - Row indexing base (0-based vs 1-based) and amount column name/format are
      unspecified and require clarification.
    - Output format for CLI execution is not specified and requires
      clarification.
    """

    raise NotImplementedError


def cmd_partition_transactions(csv_path: str, partition_period: str) -> int:
    """CLI handler for ``partition-transactions <csv_path> <partition_period>`` (stub).

    Parameters
    ----------
    csv_path:
        Path to a CSV file containing transactions.
    partition_period:
        Period specifier used to divide the transactions. The expected format
        (e.g., "monthly"/"quarterly" vs a duration expression) is not defined
        and requires clarification.

    Returns
    -------
    int
        Process exit code. The function is a stub and does not perform I/O.

    Notes
    -----
    - Mirrors the :func:`financial_analysis.api.partition_transactions` API.
    - Required date column name/format and timezone/calendar assumptions are
        unspecified and require clarification.
    - Output format for CLI execution is not specified and requires
      clarification.
    """

    raise NotImplementedError


def cmd_report_trends(csv_path: str) -> int:
    """CLI handler for ``report-trends <csv_path>`` (stub).

    Parameters
    ----------
    csv_path:
        Path to a CSV file containing transactions.

    Returns
    -------
    int
        Process exit code. The function is a stub and does not perform I/O.

    Notes
    -----
    - Mirrors the :func:`financial_analysis.api.report_trends` API.
    - Required column names (date, amount, category), output table layout,
      and rendering destination are not specified and require clarification.
    """

    raise NotImplementedError


def cmd_review_transaction_categories(
    csv_path_with_categories: str,
) -> int:
    """CLI handler for ``review-transaction-categories <csv_path_with_categories>`` (stub).

    Parameters
    ----------
    csv_path_with_categories:
        Path to a CSV containing transactions that already include category
        information.

    Returns
    -------
    int
        Process exit code. The function is a stub and does not perform I/O.

    Notes
    -----
    - Mirrors the :func:`financial_analysis.api.review_transaction_categories` API.
    - REPL interaction model (prompts, commands, confirmation flow), category
      ontology, and any normalization rules are not specified and require
      clarification.
    - Output format for CLI execution is not specified and requires
      clarification.
    """

    raise NotImplementedError
