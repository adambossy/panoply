# ruff: noqa: I001
"""CLI for the ``financial_analysis`` package.

This module exposes callable command handlers (e.g.,
``cmd_categorize_expenses``) and a Typer-based console interface. Environment
variables (notably ``OPENAI_API_KEY``) are loaded from a local ``.env`` using
``python-dotenv`` before delegating to command logic. Business logic lives in
``financial_analysis.api`` and related modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
from dotenv import load_dotenv
from typer.models import OptionInfo

from .categories import (
    load_taxonomy_from_db,
)
from .categorize import categorize_expenses, prefill_unanimous_groups_from_db


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

    # Local imports to keep CLI dependency surface minimal
    from .ingest.adapters.amex_enhanced_details_csv import (
        to_ctv_enhanced_details,
    )
    from .ingest.adapters.amex_like_csv import to_ctv as to_ctv_standard

    # Validate environment early so failures are clear
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY is not set in the environment.", file=sys.stderr)
        return 1

    # Attempt to open and parse the CSV (supports AmEx Enhanced Details with
    # preamble and the standard AmEx-like export with the header on the first
    # row). Header validation is performed inside the adapter, which will raise
    # ``csv.Error`` with an informative message when the header cannot be
    # located or required columns are missing.
    try:
        with open(csv_path, encoding="utf-8", newline="") as f:
            try:
                # Prefer Enhanced Details adapter (handles preamble and exact header).
                ctv_items = list(to_ctv_enhanced_details(f))
            except csv.Error as err:
                # Fallback: standard AmEx-like CSV where the header is on the first row.
                f.seek(0)
                reader = csv.DictReader(f)
                headers = reader.fieldnames
                required_headers = {
                    "Reference",
                    "Description",
                    "Amount",
                    "Date",
                    "Appears On Your Statement As",
                    "Extended Details",
                }
                if headers is None:
                    raise csv.Error(f"CSV appears to have no header row: {csv_path}") from err
                missing = sorted(h for h in required_headers if h not in headers)
                if missing:
                    raise csv.Error(
                        "CSV header mismatch for AmEx-like adapter. Missing columns: "
                        + ", ".join(missing)
                    ) from err
                ctv_items = list(to_ctv_standard(reader))

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

    # Load taxonomy from DB via shared helper (env DATABASE_URL is used by default)
    try:
        taxonomy: list[dict[str, Any]] = load_taxonomy_from_db(database_url=None)
    except Exception as e:
        print(f"Error: failed to load taxonomy from DB: {e}", file=sys.stderr)
        return 1

    # Call the categorization API and print results
    try:
        results = list(
            categorize_expenses(
                ctv_items,
                taxonomy=taxonomy,
            )
        )
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
    csv_path: str,
    *,
    database_url: str | None = None,
    source_provider: str = "amex",
    source_account: str | None = None,
    allow_create: bool | None = None,
) -> int:
    """Categorize a CSV, review groups interactively, and persist decisions.

    Flow
    ----
    - Load and normalize ``csv_path`` into CTV using the same adapters as
      :func:`categorize_expenses_cmd`.
    - Call :func:`financial_analysis.api.categorize_expenses` to obtain initial
      category suggestions.
    - Invoke :func:`financial_analysis.api.review_transaction_categories` with
      ``source_provider``/``source_account`` and ``database_url`` so the user can
      confirm/override categories per duplicate group and persist them
      (``category_source='manual'``, ``verified=true``).


    UI
    --
    Category selection uses a prompt_toolkit completion menu backed by the
    canonical category list from the database. The predicted category is
    pre-filled; press Enter to accept it, or press Tab/arrow keys to open and
    navigate the dropdown and Enter to confirm a different category.

    - The predicted category is pre-filled; press Enter to accept it.
    - Press Down (↓) at any time to open the dropdown. On an empty input it
      shows all categories; after typing a prefix it shows only matches.
    - As you type a strict prefix of a category, the remainder is shown inline
      as greyed-out "ghost" text. Press Tab to complete the suggestion without
      submitting; press Enter to complete and submit.
    - When multiple categories match a prefix, the inline suggestion follows
      the top candidate (list order). Use Down to open the menu and pick a
      different match.

    Requirements
    ------------
    This review flow requires database access to load the canonical category
    list (``fa_categories``) and to persist decisions. Provide a connection via
    ``--database-url`` or set ``DATABASE_URL`` in the environment, and ensure
    the workspace ``db`` package is installed/available. If unavailable, the
    command will print a clear error and exit non‑zero (it will not crash at
    import time).
    """

    import csv
    import os
    import sys
    # No ThreadPoolExecutor here by design: batching is handled inside
    # `categorize_expenses` via page_size + p_map.

    # Load .env here as a defensive guarantee (in addition to the Typer wrapper
    # and root callback) so env-dependent checks work even if this function is
    # called directly.
    load_dotenv(override=False)

    from .api import review_transaction_categories
    from .ingest.adapters.amex_enhanced_details_csv import to_ctv_enhanced_details
    from .ingest.adapters.amex_like_csv import to_ctv as to_ctv_standard

    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY is not set in the environment.", file=sys.stderr)
        return 1

    # Load CSV → CTV (robust detection: scan small prefix for Enhanced Details token)
    try:
        with open(csv_path, encoding="utf-8", newline="") as f:
            head = f.read(8192)
            f.seek(0)
            if "Extended Details" in head:
                # Enhanced Details export (may include a preamble before the header)
                ctv_items = list(to_ctv_enhanced_details(f))
            else:
                reader = csv.DictReader(f)
                headers_set = set(reader.fieldnames or [])
                if not headers_set:
                    raise csv.Error(f"CSV appears to have no header row: {csv_path}")
                required_headers = {
                    "Reference",
                    "Description",
                    "Amount",
                    "Date",
                    "Appears On Your Statement As",
                }
                missing = sorted(h for h in required_headers if h not in headers_set)
                if missing:
                    raise csv.Error(
                        "CSV header mismatch for AmEx-like adapter. Missing columns: "
                        + ", ".join(missing)
                    )
                ctv_items = list(to_ctv_standard(reader))
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

    total = len(ctv_items)
    if total == 0:
        print("No transactions to review.")
        return 0

    # DB-first prefill: resolve groups that have a unanimous DB category
    try:
        prefilled_positions, prefilled_groups = prefill_unanimous_groups_from_db(
            ctv_items,
            database_url=database_url,
            source_provider=source_provider,
            source_account=source_account,
        )
    except Exception as e:
        print(f"Error: DB prefill failed: {e}", file=sys.stderr)
        return 1

    # Build unresolved subset in original order
    unresolved_indices: list[int] = [i for i in range(total) if i not in (prefilled_positions)]
    unresolved_ctv: list = [ctv_items[i] for i in unresolved_indices]

    # When everything was resolved from DB, jump straight to the (no-op) review
    # with an empty list so the pre-review summary/exit path remains familiar.
    if len(unresolved_ctv) == 0:
        try:
            review_transaction_categories(
                [],
                source_provider=source_provider,
                source_account=source_account,
                database_url=database_url,
                prefilled_groups=prefilled_groups,
                allow_create=allow_create,
            )
        except Exception as e:
            print(f"Error: review failed: {e}", file=sys.stderr)
            return 1
        return 0

    # Load the canonical taxonomy from the DB (uses provided database_url)
    try:
        taxonomy: list[dict[str, Any]] = load_taxonomy_from_db(database_url=database_url)
    except Exception as e:
        print(f"Error: failed to load taxonomy from DB: {e}", file=sys.stderr)
        return 1

    # Light status line so operators know we're working while pages run in parallel
    print(f"Categorizing {len(unresolved_ctv)} unresolved items…")

    try:
        # Categorize only unresolved items using dataset-level cache. This defers
        # all batching to `categorize_expenses` (pages of 10 via p_map).
        all_unresolved_suggestions = categorize_expenses(
            transactions=unresolved_ctv,
            taxonomy=taxonomy,
            source_provider=source_provider,
        )
    except Exception as e:
        print(f"Error: categorization failed: {e}", file=sys.stderr)
        return 1

    # Sanity check: results must align with unresolved inputs
    if len(all_unresolved_suggestions) != len(unresolved_ctv):
        print(
            "Error: internal alignment error (unresolved results size mismatch)",
            file=sys.stderr,
        )
        return 1

    # Auto-apply high-confidence suggestions (Issue #94 follow-up):
    # Persist any suggestion with effective confidence > 0.7. Only update rows
    # that are currently unverified to avoid clobbering operator-reviewed categories.
    try:
        from db.client import session_scope
        from .persistence import auto_persist_high_confidence

        with session_scope(database_url=database_url) as session:
            applied = auto_persist_high_confidence(
                session,
                source_provider=source_provider,
                source_account=source_account,
                suggestions=all_unresolved_suggestions,
                min_confidence=0.7,
            )
        if applied:
            print(
                f"Auto-applied {applied} high-confidence suggestions (> 0.7)."
            )
    except Exception as e:
        print(
            f"Warning: failed to auto-apply high-confidence suggestions: {e}",
            file=sys.stderr,
        )

    # Begin review for unresolved groups only (pass only the unresolved subset
    # so the interactive UI processes fewer groups as intended).
    try:
        review_transaction_categories(
            all_unresolved_suggestions,
            source_provider=source_provider,
            source_account=source_account,
            database_url=database_url,
            prefilled_groups=prefilled_groups,
            allow_create=allow_create,
        )
    except Exception as e:
        print(f"Error: review failed: {e}", file=sys.stderr)
        return 1

    return 0


# ---- Typer-based console interface -------------------------------------------


app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help=(
        "Categorize expenses from an AmEx-like CSV using OpenAI (Responses API). "
        "Loads OPENAI_API_KEY from a local .env before running."
    ),
)


@app.command("categorize-expenses")
def categorize_expenses_cmd(
    csv_path: Annotated[Path, CSV_PATH_OPTION],
    *,
    persist: bool = typer.Option(
        False, help="Persist transactions and category updates to the database."
    ),
    database_url: str | None = typer.Option(
        None, help="Override DATABASE_URL (falls back to env var)."
    ),
    source_provider: str = typer.Option(
        "amex",
        help="Source provider identifier for persistence (e.g., amex, chase, venmo).",
    ),
    source_account: str | None = typer.Option(
        None, help="Optional source account identifier for persistence."
    ),
) -> int:
    """Categorize a CSV and optionally persist before/after categorization."""

    load_dotenv()

    # Deferred imports to keep CLI startup fast
    import csv
    import os
    import sys

    from .ingest.adapters.amex_enhanced_details_csv import to_ctv_enhanced_details
    from .ingest.adapters.amex_like_csv import to_ctv as to_ctv_standard

    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY is not set in the environment.", file=sys.stderr)
        return 1

    # Load and normalize the CSV into CTV rows
    try:
        with open(csv_path, encoding="utf-8", newline="") as f:
            try:
                ctv_items = list(to_ctv_enhanced_details(f))
            except csv.Error as err:
                f.seek(0)
                reader = csv.DictReader(f)
                headers = reader.fieldnames
                required_headers = {
                    "Reference",
                    "Description",
                    "Amount",
                    "Date",
                    "Appears On Your Statement As",
                    "Extended Details",
                }
                if headers is None:
                    raise csv.Error(f"CSV appears to have no header row: {csv_path}") from err
                missing = sorted(h for h in required_headers if h not in headers)
                if missing:
                    raise csv.Error(
                        "CSV header mismatch for AmEx-like adapter. Missing columns: "
                        + ", ".join(missing)
                    ) from err
                ctv_items = list(to_ctv_standard(reader))
    except FileNotFoundError:
        print(f"Error: File not found: {csv_path}", file=sys.stderr)
        return 1
    except PermissionError:
        print(f"Error: Permission denied: {csv_path}", file=sys.stderr)
        return 1
    except csv.Error as e:
        print(f"Error: Failed to parse CSV: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: Unexpected failure reading '{csv_path}': {e}", file=sys.stderr)
        return 1

    # When persisting, write transactions first in a short transaction to avoid
    # losing ingestion if categorization fails later.
    if persist:
        try:
            from db.client import session_scope
            from .persistence import upsert_transactions

            with session_scope(database_url=database_url) as session:
                upsert_transactions(
                    session,
                    source_provider=source_provider,
                    source_account=source_account,
                    transactions=ctv_items,
                )
        except Exception as e:
            print(f"Error: persistence (upsert) failed: {e}", file=sys.stderr)
            return 1

    # Load taxonomy from DB via shared helper (respects provided database_url)
    try:
        taxonomy: list[dict[str, Any]] = load_taxonomy_from_db(database_url=database_url)
    except Exception as e:
        print(f"Error: failed to load taxonomy from DB: {e}", file=sys.stderr)
        return 1

    # Compute categories (network-bound) outside of any DB transaction.
    try:
        results = list(
            categorize_expenses(
                ctv_items,
                taxonomy=taxonomy,
            )
        )
    except Exception as e:
        print(f"Error: categorize_expenses failed: {e}", file=sys.stderr)
        return 1

    # Apply category updates in a second short transaction when persisting.
    if persist:
        try:
            from db.client import session_scope
            from .persistence import apply_category_updates

            with session_scope(database_url=database_url) as session:
                apply_category_updates(
                    session,
                    source_provider=source_provider,
                    categorized=results,
                    category_source="llm",
                    category_confidence=None,
                )
        except Exception as e:
            print(f"Error: persistence (category updates) failed: {e}", file=sys.stderr)
            return 1

    # Print results as "<id>\t<category>" per existing contract
    for row in results:
        tx_id = row.transaction.get("id") if isinstance(row.transaction, dict) else None
        print(f"{tx_id or ''}\t{row.category}")

    return 0


@app.command("review-transaction-categories")
def review_transaction_categories_cmd(
    csv_path: Annotated[Path, CSV_PATH_OPTION],
    *,
    database_url: str | None = typer.Option(
        None, help="Override DATABASE_URL (falls back to env var)."
    ),
    source_provider: str = typer.Option(
        "amex",
        help="Source provider identifier for persistence (e.g., amex, chase, venmo).",
    ),
    source_account: str | None = typer.Option(
        None, help="Optional source account identifier for persistence."
    ),
    allow_create: bool | None = typer.Option(
        None,
        help=(
            "Enable in-flow category creation (default true). "
            "Override with env FA_ALLOW_CATEGORY_CREATE=0."
        ),
    ),
) -> int:
    load_dotenv()
    import os

    # Resolve default from env when option omitted
    if allow_create is None:
        env_val = os.getenv("FA_ALLOW_CATEGORY_CREATE")
        if env_val is not None:
            v = env_val.strip().lower()
            if v in {"0", "false", "no"}:
                allow_create = False
            elif v in {"1", "true", "yes"}:
                allow_create = True
            else:
                allow_create = None
    return cmd_review_transaction_categories(
        str(csv_path),
        database_url=database_url,
        source_provider=source_provider,
        source_account=source_account,
        allow_create=allow_create,
    )


# Module-level option object to satisfy ruff B008 (no calls in parameter
# defaults). Typer will inspect this when used as a default value below.
CSV_PATH_OPTION: OptionInfo = typer.Option(
    ...,  # required
    "--csv-path",
    help="Path to an AmEx-like CSV file to categorize",
    dir_okay=False,
    file_okay=True,
    exists=False,  # allow non-existent here; the handler will report nice errors
    readable=True,
)


if __name__ == "__main__":  # pragma: no cover - exercised via uv tool script
    # Running as a module: `python -m financial_analysis.cli`
    app()
