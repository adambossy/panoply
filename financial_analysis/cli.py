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
    - ``partition-transactions <csv_path> [--years N] [--months N]``
      ``[--weeks N] [--days N]``
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
    """Categorize expenses from a CSV file and print results to stdout.

    Behavior
    --------
    - Reads ``csv_path`` as an AmEx-like CSV export.
    - Converts rows to Canonical Transaction View (CTV) using the existing
      adapter at ``financial_analysis.ingest.adapters.amex_like_csv``.
    - Invokes :func:`financial_analysis.api.categorize_expenses` with the CTV
      sequence.
    - Writes one line per transaction to stdout in input order, formatted as
      ``"<id>\t<category>"`` where ``<id>`` is empty when not present.

    Errors are written to stderr and the function returns a non‑zero exit
    status. On success, returns ``0``.

    Parameters
    ----------
    csv_path:
        Filesystem path to the CSV file.
    """

    import csv
    import os
    import sys
    from collections.abc import Iterable

    # Local imports to keep CLI dependency surface minimal
    from .api import categorize_expenses
    from .ingest.adapters.amex_like_csv import to_ctv

    # Validate environment early so failures are clear
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY is not set in the environment.", file=sys.stderr)
        return 1

    # Attempt to open and parse the CSV
    try:
        with open(csv_path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)

            # Verify required headers for the AmEx-like adapter
            required_headers = {
                "Reference",
                "Description",
                "Amount",
                "Date",
                "Appears On Your Statement As",
                "Extended Details",
            }
            headers: Iterable[str] | None = reader.fieldnames
            if headers is None:
                print(
                    f"Error: CSV appears to have no header row: {csv_path}",
                    file=sys.stderr,
                )
                return 1
            missing = sorted(h for h in required_headers if h not in headers)
            if missing:
                print(
                    "Error: CSV header mismatch for AmEx-like adapter. Missing columns: "
                    + ", ".join(missing),
                    file=sys.stderr,
                )
                return 1

            # Convert rows to CTV and realize as a list to preserve order
            ctv_items = list(to_ctv(reader))

    except FileNotFoundError:
        print(f"Error: File not found: {csv_path}", file=sys.stderr)
        return 1
    except PermissionError:
        print(f"Error: Permission denied: {csv_path}", file=sys.stderr)
        return 1
    except csv.Error as e:
        print(f"Error: Failed to parse CSV: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # pragma: no cover - defensive
        print(f"Error: Unexpected failure reading '{csv_path}': {e}", file=sys.stderr)
        return 1

    # Call the categorization API and print results
    try:
        results = list(categorize_expenses(ctv_items))
    except Exception as e:
        # Provide a concise message; the API validates inputs and may raise
        # ValueError/TypeError for schema or OpenAI/network issues.
        print(f"Error: categorize_expenses failed: {e}", file=sys.stderr)
        return 1

    # Emit one line per transaction: "<id>\t<category>"
    for row in results:
        tx_id = row.transaction.get("id") if isinstance(row.transaction, dict) else None
        print(f"{tx_id or ''}\t{row.category}")

    return 0


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
    - Mirrors the :func:`financial_analysis.api.identify_refunds` feature.
    - Refund matches are represented as pairs of full
      :data:`~financial_analysis.models.TransactionRecord` objects (see
      :class:`~financial_analysis.models.RefundMatch`), not row indices.
    - The amount column name/format and any date schema or disambiguation rules
      are unspecified and require clarification.
    - Output format for CLI execution is not specified and requires
      clarification.
    """

    raise NotImplementedError


def cmd_partition_transactions(
    csv_path: str,
    *,
    years: int | None = None,
    months: int | None = None,
    weeks: int | None = None,
    days: int | None = None,
) -> int:
    """CLI handler for the ``partition-transactions`` subcommand (stub).

    Usage
    -----
    ``partition-transactions <csv_path> [--years N] [--months N] [--weeks N] [--days N]``

    Parameters
    ----------
    csv_path:
        Path to a CSV file containing transactions.
    years:
        Optional integer number of years per partition; maps directly to
        :class:`financial_analysis.models.PartitionPeriod.years`.
    months:
        Optional integer number of months per partition; maps directly to
        :class:`financial_analysis.models.PartitionPeriod.months`.
    weeks:
        Optional integer number of weeks per partition; maps directly to
        :class:`financial_analysis.models.PartitionPeriod.weeks`.
    days:
        Optional integer number of days per partition; maps directly to
        :class:`financial_analysis.models.PartitionPeriod.days`.

    Any combination of these flags may be provided (e.g., ``--months 3 --weeks 2``).

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


# ---- Console entrypoint for `categorize-expenses` ----------------------------


def _load_dotenv_from_cwd_if_present() -> None:
    """Load OPENAI_API_KEY from a .env file in the current working directory.

    This is a tiny, dependency-free loader to satisfy the requirement that the
    command observes OPENAI_API_KEY provided via a repository-root `.env` even
    when the execution environment doesn't auto-load it.

    Behavior:
    - Only sets environment variables that are not already present.
    - Reads KEY=VALUE pairs; ignores blank lines and lines starting with `#`.
    - Trims surrounding single or double quotes around the VALUE.
    - Only affects the current process (no filesystem writes).
    """

    import os
    from pathlib import Path

    if "OPENAI_API_KEY" in os.environ:
        return
    env_path = Path.cwd() / ".env"
    if not env_path.is_file():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            key = k.strip()
            if key != "OPENAI_API_KEY":
                continue
            val = v.strip()
            if (val.startswith('"') and val.endswith('"')) or (
                val.startswith("'") and val.endswith("'")
            ):
                val = val[1:-1]
            if key not in os.environ:
                os.environ[key] = val
    except Exception:
        # Silent best-effort; cmd handler will validate the env var and report errors.
        return


def main_categorize_expenses(argv: list[str] | None = None) -> int:
    """Console entrypoint for `categorize-expenses`.

    Parses `--csv-path` and delegates to :func:`cmd_categorize_expenses`.
    Returns the integer exit code produced by the command handler.
    """

    import argparse
    import sys

    _load_dotenv_from_cwd_if_present()

    parser = argparse.ArgumentParser(prog="categorize-expenses")
    parser.add_argument(
        "--csv-path",
        required=True,
        help="Path to an AmEx-like CSV file to categorize",
    )

    # argparse calls sys.exit on error; convert that into an int return code so
    # console-script wrappers can exit cleanly with that code.
    try:
        ns = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 2

    return cmd_categorize_expenses(ns.csv_path)
