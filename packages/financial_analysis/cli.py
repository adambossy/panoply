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
from collections.abc import Mapping, Sequence

import typer
from dotenv import load_dotenv
from typer.models import OptionInfo
# Move selected imports to top-level per review feedback (keeps startup reasonable)
from db.client import session_scope  # noqa: F401  (used in commands)
from sqlalchemy import select  # noqa: F401
from db.models.finance import FaCategory  # noqa: F401

# Persistence-heavy helpers remain imported lazily within commands to keep startup fast.

from .logging_setup import configure_logging


# ---- Small module‑level helpers used by CLI commands -------------------------


def _resolve_max_workers(n_chunks: int) -> int:
    """Resolve a conservative worker count for chunk categorization.

    Honors the optional ``FA_CATEGORY_MAX_WORKERS`` env var, caps to ``n_chunks``
    and to 32 to avoid oversubscription/rate limits, and ensures a minimum of 1.
    """

    import os  # defer import to keep module import surface minimal

    _env_workers = os.getenv("FA_CATEGORY_MAX_WORKERS")
    try:
        max_workers = int(_env_workers) if _env_workers else None
    except Exception:
        max_workers = None

    if max_workers is not None and max_workers > 0:
        return max(1, min(max_workers, n_chunks, 32))
    # Default: modest parallelism to be gentle on API rate limits
    return max(1, min(8, n_chunks))


def _compute_one(
    idx: int,
    *,
    dataset_id: str,
    ctv_items: list,
    source_provider: str,
    chunk_size: int,
    allowed_categories: tuple[str, ...],
    taxonomy_hierarchy: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[int, list, float]:
    """Compute a single categorization chunk and return timing info.

    Returns a tuple ``(idx, items, seconds)`` for easy assembly and logging.
    """

    import time

    # Local import to keep CLI startup fast and avoid global side effects
    from .batching import get_or_compute_chunk

    t0_local = time.perf_counter()
    items = list(
        get_or_compute_chunk(
            dataset_id,
            idx,
            ctv_items,
            source_provider=source_provider,
            chunk_size=chunk_size,
            allowed_categories=allowed_categories,
            taxonomy_hierarchy=taxonomy_hierarchy,
        )
    )
    return idx, items, time.perf_counter() - t0_local


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
    from .categorize import categorize_expenses
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

    # Load allowed categories and taxonomy (requires DATABASE_URL); sanitize values
    try:
        with session_scope(database_url=None) as session:  # DATABASE_URL from env
            rows = session.execute(select(FaCategory)).scalars().all()
            # Map codes to rows for quick lookup
            code_to_row = {
                (r.code or "").strip(): r
                for r in rows
                if isinstance(getattr(r, "code", None), str) and r.code and r.code.strip()
            }
            # Sanitize, de-duplicate, and sort deterministically
            allowed_set = set(code_to_row.keys())
            if not allowed_set:
                raise RuntimeError("no valid categories present in fa_categories")
            # Select initial set and ensure parents are included when present in DB
            selected: set[str] = set(allowed_set)
            stack = list(selected)
            while stack:
                c = stack.pop()
                parent = (getattr(code_to_row.get(c), "parent_code", None) or "").strip() or None
                if parent and parent not in selected and parent in code_to_row:
                    selected.add(parent)
                    stack.append(parent)
            allowed_list = sorted(selected)
            taxonomy: list[dict[str, Any]] = [
                {
                    "code": c,
                    "display_name": (getattr(code_to_row[c], "display_name", c) or "").strip() or c,
                    "parent_code": (getattr(code_to_row[c], "parent_code", None) or "").strip() or None,
                }
                for c in allowed_list
            ]
    except Exception as e:
        print(f"Error: failed to load categories from DB: {e}", file=sys.stderr)
        return 1

    # Call the categorization API and print results
    try:
        results = list(
            categorize_expenses(
                ctv_items,
                allowed_categories=tuple(allowed_list),
                taxonomy_hierarchy=taxonomy,
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
    auto_confirm_dupes: bool = False,
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
    from concurrent.futures import ThreadPoolExecutor, as_completed

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

    # Categorize in chunks with on-disk caching and only start review once all
    # batches have finished (per Issue #70).
    try:
        from .batching import compute_dataset_id, total_chunks_for
    except Exception as e:
        print(f"Error: failed to import batching helpers: {e}", file=sys.stderr)
        return 1

    total = len(ctv_items)
    if total == 0:
        print("No transactions to review.")
        return 0

    # Chunk size: fixed at 250 by default; allow a dev override via env
    _env_sz = os.getenv("FA_REVIEW_CHUNK_SIZE")
    try:
        chunk_size = int(_env_sz) if _env_sz else 250
        if chunk_size <= 0:
            raise ValueError
    except Exception:
        chunk_size = 250

    # Load the canonical category list and the taxonomy hierarchy from the DB.
    try:
        with session_scope(database_url=database_url) as session:
            rows = session.execute(select(FaCategory)).scalars().all()
            # Sanitize, dedupe, sort deterministically
            allowed_set = {
                r.code.strip()
                for r in rows
                if isinstance(getattr(r, "code", None), str) and r.code and r.code.strip()
            }
            allowed_categories_list = sorted(allowed_set)
            if not allowed_categories_list:
                print(
                    "Error: no valid categories present in fa_categories; cannot proceed",
                    file=sys.stderr,
                )
                return 1
            taxonomy_h: list[dict[str, Any]] = [
                {
                    "code": (r.code or "").strip(),
                    "display_name": (getattr(r, "display_name", r.code) or "").strip()
                    or (r.code or "").strip(),
                    "parent_code": (getattr(r, "parent_code", None) or "").strip() or None,
                }
                for r in sorted(rows, key=lambda x: ((getattr(x, "code", "") or "").strip()))
                if isinstance(getattr(r, "code", None), str)
                and r.code
                and r.code.strip() in allowed_set
            ]
    except Exception as e:
        print(f"Error: failed to load categories from DB: {e}", file=sys.stderr)
        return 1
    allowed_categories: tuple[str, ...] = tuple(allowed_categories_list)

    dataset_id = compute_dataset_id(
        ctv_items,
        source_provider=source_provider,
        allowed_categories=allowed_categories,
        taxonomy_hierarchy=taxonomy_h,
    )
    n_chunks = total_chunks_for(total, chunk_size=chunk_size)

    print()
    print(f"Waiting for LLM ({n_chunks} chunks)…")

    # Compute all chunks up front in parallel; keep cache semantics unchanged.
    # Print a short timing line as each batch completes. Preserve overall
    # output order by assembling results by chunk index after completion.
    all_suggestions: list = []
    try:
        # Bounded worker pool; default to a conservative level unless overridden.
        max_workers = _resolve_max_workers(n_chunks)

        results_by_idx: dict[int, list] = {}

        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fa-chunk") as ex:
            fut_to_idx = {}
            for k in range(n_chunks):
                fut = ex.submit(
                    _compute_one,
                    k,
                    dataset_id=dataset_id,
                    ctv_items=ctv_items,
                    source_provider=source_provider,
                    chunk_size=chunk_size,
                    allowed_categories=allowed_categories,
                    taxonomy_hierarchy=taxonomy_h,
                )
                fut_to_idx[fut] = k

            for fut in as_completed(fut_to_idx):
                try:
                    idx, items_k, dt = fut.result()
                except Exception as e:
                    failed_idx = fut_to_idx.get(fut, -1)
                    batch_no = failed_idx + 1 if failed_idx >= 0 else 0
                    msg = f"Error: categorization failed on batch {batch_no}/{n_chunks}: {e}"
                    print(msg, file=sys.stderr)
                    return 1
                results_by_idx[idx] = items_k
                print(f"Batch {idx + 1}/{n_chunks} finished in {dt:.1f}s")

        # Assemble in index order to preserve deterministic output ordering
        for k in range(n_chunks):
            all_suggestions.extend(results_by_idx[k])
    except Exception as e:
        print(f"Error: categorization failed: {e}", file=sys.stderr)
        return 1

    # Begin a single consolidated review pass.
    try:
        review_transaction_categories(
            all_suggestions,
            source_provider=source_provider,
            source_account=source_account,
            database_url=database_url,
            allow_create=allow_create,
            auto_confirm_dupes=auto_confirm_dupes,
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

    from .api import categorize_expenses
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

    # Load allowed categories and taxonomy (requires DATABASE_URL); sanitize values
    try:
        with session_scope(database_url=database_url) as session:
            rows = session.execute(select(FaCategory)).scalars().all()
            # Map codes to rows for quick lookup
            code_to_row = {
                (r.code or "").strip(): r
                for r in rows
                if isinstance(getattr(r, "code", None), str) and r.code and r.code.strip()
            }
            # Sanitize, de-duplicate, and sort deterministically
            selected: set[str] = set(code_to_row.keys())
            if not selected:
                raise RuntimeError("no valid categories present in fa_categories")
            # Ensure parents exist for any children present (if present in DB)
            stack = list(selected)
            while stack:
                c = stack.pop()
                parent = (getattr(code_to_row.get(c), "parent_code", None) or "").strip() or None
                if parent and parent not in selected and parent in code_to_row:
                    selected.add(parent)
                    stack.append(parent)
            allowed_list = sorted(selected)
            taxonomy: list[dict[str, Any]] = [
                {
                    "code": c,
                    "display_name": (getattr(code_to_row[c], "display_name", c) or "").strip() or c,
                    "parent_code": (getattr(code_to_row[c], "parent_code", None) or "").strip() or None,
                }
                for c in allowed_list
            ]
    except Exception as e:
        print(f"Error: failed to load categories from DB: {e}", file=sys.stderr)
        return 1

    # Compute categories (network-bound) outside of any DB transaction.
    try:
        results = list(
            categorize_expenses(
                ctv_items,
                allowed_categories=tuple(allowed_list),
                taxonomy_hierarchy=taxonomy,
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
    auto_confirm_dupes: bool = typer.Option(
        False,
        help=(
            "Automatically confirm applying the chosen category to session duplicates "
            "(based on normalized merchant/description)."
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
        auto_confirm_dupes=auto_confirm_dupes,
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


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
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
) -> None:
    """Root command.

    Loads ``.env`` from the current working directory (without overriding any
    already-set environment variables) and delegates to
    :func:`cmd_categorize_expenses` when no subcommand is invoked.
    """

    # Load environment from .env in CWD (override=False to keep existing env)
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)

    # Central logging setup so child loggers inherit configuration
    configure_logging()

    if ctx.invoked_subcommand is None:
        # No subcommand provided - show help
        typer.echo("No subcommand provided. Use --help to see available commands.")
        raise typer.Exit(1)


if __name__ == "__main__":  # pragma: no cover - exercised via uv tool script
    # Running as a module: `python -m financial_analysis.cli`
    app()
