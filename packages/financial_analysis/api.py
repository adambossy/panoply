"""Public API interfaces and orchestration for the ``financial_analysis`` package.

This module provides the implemented categorization flow
(:func:`categorize_expenses`) that prepares Canonical Transaction View (CTV)
records, calls the OpenAI Responses API, and returns aligned results. Other
interfaces remain stubs and raise ``NotImplementedError`` by design.
"""

from __future__ import annotations

import json
import logging
import math
import random
import time
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, cast

from openai import OpenAI
from openai.types.responses import ResponseTextConfigParam

# Internal helpers (implementation modules)
from . import prompting
from .categorization import (
    ALLOWED_CATEGORIES,
    ensure_valid_ctv_descriptions,
    parse_and_align_categories,
)
from .models import (
    CategorizedTransaction,
    PartitionPeriod,
    RefundMatch,
    TransactionPartitions,
    Transactions,
)

# ---------------------------------------------------------------------------
# Module configuration (tunable, but stable defaults)
# ---------------------------------------------------------------------------

# Default page size for LLM categorization; exposed as the default for the
# public kw-only parameter on categorize_expenses.
PAGE_SIZE_CATEGORIZE: int = 100

# Bounded concurrency for in-flight LLM page requests.
CONCURRENCY_CATEGORIZE: int = 4

# Retry policy (per page): total attempts incl. the first try.
_MAX_ATTEMPTS_PER_PAGE: int = 3
_BACKOFF_SCHEDULE_SEC: tuple[float, ...] = (0.5, 2.0)
_JITTER_PCT: float = 0.20

logger = logging.getLogger("financial_analysis.categorize")

# Configure logging if not already configured
if not logger.handlers:
    # Set up a simple console handler for this logger
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    # Prevent propagation to avoid duplicate logs
    logger.propagate = False


def _extract_response_json_mapping(resp: Any) -> Mapping[str, Any]:
    """Return the decoded JSON mapping from an OpenAI Responses SDK result.

    Behavior (preserved from the original inline logic in ``categorize_expenses``):
    - Try the SDK convenience property ``resp.output_text`` first.
    - Fall back to inspecting the first output item's ``content[0].text`` when
      necessary.
    - If no usable text is found, raise ``ValueError`` with the original
      message.
    - ``json.loads`` the located text; on failure, raise ``ValueError`` with the
      original message.
    """

    # Prefer the SDK's convenience property; fall back to inspecting the first
    # message/output item if necessary.
    text: str | None = getattr(resp, "output_text", None)
    if not text:
        try:
            # `resp.output` is a list of items; when present, the first item is
            # typically a message with `content[0].text` holding the string.
            first = resp.output[0] if getattr(resp, "output", None) else None
            content = getattr(first, "content", None)
            if content and len(content) > 0:
                maybe_text = getattr(content[0], "text", None)
                if isinstance(maybe_text, str):
                    text = maybe_text
        except Exception:  # noqa: BLE001 - defensive; shape differences are tolerated
            text = None
    if not text or not isinstance(text, str):
        raise ValueError("Unexpected Responses API shape; unable to locate text output")

    try:
        decoded: Mapping[str, Any] = json.loads(text)
    except json.JSONDecodeError as e:  # pragma: no cover - minimal defensive path
        raise ValueError("Model output was not valid JSON per the requested schema") from e

    return decoded


def categorize_expenses(
    transactions: Transactions,
    *,
    page_size: int = PAGE_SIZE_CATEGORIZE,
) -> Iterable[CategorizedTransaction]:
    """Categorize expenses via OpenAI Responses API (model: ``gpt-5``).

    Behavior:
    - Accepts an iterable of Canonical Transaction View (CTV) mapping objects.
    - Validates that each item has a non-empty ``description`` after trimming.
    - Pages the input (contiguous slices of the current input order) so that no
      request exceeds ``page_size`` items. Pages are processed concurrently with
      a bounded level of 4 in-flight LLM requests. Global output order is
      preserved regardless of per-page completion order.
    - For each page, builds a CTV list with page‑local ``idx`` (0..page_len‑1),
      constructs prompts and a strict JSON schema, invokes the OpenAI Responses
      API, and parses/validates the result, aligning by page‑local ``idx`` back
      to absolute positions.
    - Returns an iterable of :class:`CategorizedTransaction` in the exact input
      order, where ``transaction`` is the original mapping object, unmodified.
    """

    logger.info("categorize_expenses:function_start page_size=%d", page_size)

    # Coerce input to a concrete sequence to preserve order and allow indexing.
    original_seq_any = list(transactions)
    if not all(isinstance(item, Mapping) for item in original_seq_any):
        raise TypeError(
            "categorize_expenses expects each transaction to be a mapping (CTV) with keys "
            "like 'id', 'description', 'amount', 'date', 'merchant', 'memo'."
        )
    original_seq: list[Mapping[str, Any]] = list(original_seq_any)  # precise type

    n_total = len(original_seq)

    # Early exit: empty input makes no LLM calls and returns [].
    if n_total == 0:
        return []

    # Fail fast on clearly invalid inputs before issuing any LLM calls.
    ctv_for_validation: list[dict[str, Any]] = []
    for idx, record in enumerate(original_seq):
        ctv_for_validation.append(
            {
                "idx": idx,
                "id": record.get("id"),
                "description": record.get("description"),
                "amount": record.get("amount"),
                "date": record.get("date"),
                "merchant": record.get("merchant"),
                "memo": record.get("memo"),
            }
        )
    ensure_valid_ctv_descriptions(ctv_for_validation)

    # Pagination math over the current input order (no sorting or reordering).
    if not isinstance(page_size, int) or page_size <= 0:
        raise ValueError("page_size must be a positive integer")
    pages_total = math.ceil(n_total / page_size)

    logger.info(
        "categorize_expenses:start pages_total=%d total_items=%d page_size=%d concurrency=%d",
        pages_total,
        n_total,
        page_size,
        CONCURRENCY_CATEGORIZE,
    )

    # Static per-call components reused across pages.
    system_instructions = prompting.build_system_instructions()
    response_format = prompting.build_response_format(ALLOWED_CATEGORIES)
    text_cfg: ResponseTextConfigParam = cast(ResponseTextConfigParam, {"format": response_format})

    categories_by_abs_idx: list[str | None] = [None] * n_total

    def _is_retryable(exc: BaseException) -> bool:
        # Retry on common transient HTTP statuses and JSON/schema drift.
        sc = getattr(exc, "status_code", None)
        if isinstance(sc, int) and (sc == 429 or 500 <= sc < 600):
            return True
        if isinstance(exc, ValueError):  # parse_and_align / JSON decode
            return True
        return False

    def _backoff_sleep(attempt_no: int) -> None:
        # attempt_no is 1-based; delay before the next try.
        if attempt_no - 1 < len(_BACKOFF_SCHEDULE_SEC):
            base = _BACKOFF_SCHEDULE_SEC[attempt_no - 1]
        else:
            base = _BACKOFF_SCHEDULE_SEC[-1]
        jitter = base * _JITTER_PCT
        delay = base + random.uniform(-jitter, jitter)
        time.sleep(max(0.0, delay))

    def _process_page(page_index: int, base: int, end: int) -> tuple[int, int, list[str]]:
        count = end - base
        logger.info(
            "categorize_expenses:page_start page_index=%d base=%d end=%d count=%d",
            page_index,
            base,
            end,
            count,
        )

        # Build page-local CTV list with idx 0..count-1 in current order.
        ctv_page: list[dict[str, Any]] = []
        for local_idx, record in enumerate(original_seq[base:end]):
            ctv_page.append(
                {
                    "idx": local_idx,
                    "id": record.get("id"),
                    "description": record.get("description"),
                    "amount": record.get("amount"),
                    "date": record.get("date"),
                    "merchant": record.get("merchant"),
                    "memo": record.get("memo"),
                }
            )
        ctv_json = prompting.serialize_ctv_to_json(ctv_page)
        user_content = prompting.build_user_content(ctv_json, allowed_categories=ALLOWED_CATEGORIES)

        logger.debug(
            "categorize_expenses:page_prepared page_index=%d ctv_count=%d content_length=%d",
            page_index,
            len(ctv_page),
            len(user_content),
        )

        attempt = 1
        while True:
            t0 = time.perf_counter()
            try:
                logger.info(
                    (
                        "categorize_expenses:page_attempt page_index=%d base=%d count=%d "
                        "attempt=%d max=%d"
                    ),
                    page_index,
                    base,
                    count,
                    attempt,
                    _MAX_ATTEMPTS_PER_PAGE,
                )
                # Create client per worker for thread safety.
                client = OpenAI()
                resp = client.responses.create(
                    model="gpt-5",
                    instructions=system_instructions,
                    input=user_content,
                    text=text_cfg,
                )
                decoded = _extract_response_json_mapping(resp)
                page_categories = parse_and_align_categories(decoded, num_items=count)
                dt_ms = (time.perf_counter() - t0) * 1000.0
                logger.info(
                    (
                        "categorize_expenses:page_success page_index=%d base=%d count=%d "
                        "latency_ms=%.2f retries_used=%d"
                    ),
                    page_index,
                    base,
                    count,
                    dt_ms,
                    attempt - 1,
                )
                logger.info(
                    "categorize_expenses:page_complete page_index=%d categories_returned=%d",
                    page_index,
                    len(page_categories),
                )
                return (page_index, base, page_categories)
            except Exception as e:  # noqa: BLE001
                dt_ms = (time.perf_counter() - t0) * 1000.0
                if attempt >= _MAX_ATTEMPTS_PER_PAGE or not _is_retryable(e):
                    logger.error(
                        (
                            "categorize_expenses:page_failed_terminal page_index=%d base=%d "
                            "count=%d latency_ms=%.2f error=%s"
                        ),
                        page_index,
                        base,
                        count,
                        dt_ms,
                        e.__class__.__name__,
                    )
                    # Preserve ValueError semantics for parsing/validation failures
                    # to keep backward-compatibility with callers/tests.
                    if isinstance(e, ValueError):
                        raise e
                    raise RuntimeError(
                        f"categorize_expenses failed for page {page_index} "
                        f"(base={base}, count={count}): {e}"
                    ) from e
                logger.warning(
                    (
                        "categorize_expenses:page_retry page_index=%d base=%d count=%d "
                        "latency_ms=%.2f error=%s attempt=%d"
                    ),
                    page_index,
                    base,
                    count,
                    dt_ms,
                    e.__class__.__name__,
                    attempt,
                )
                _backoff_sleep(attempt)
                attempt += 1

    # Submit all pages to a bounded pool and aggregate as they complete.
    futures: list[Any] = []
    logger.info(
        "categorize_expenses:submitting_pages pages_total=%d concurrency=%d",
        pages_total,
        CONCURRENCY_CATEGORIZE,
    )

    with ThreadPoolExecutor(max_workers=CONCURRENCY_CATEGORIZE) as pool:
        try:
            # Submit all page processing tasks
            for k in range(pages_total):
                base = k * page_size
                end = min(base + page_size, n_total)
                future = pool.submit(_process_page, k, base, end)
                futures.append(future)
                logger.debug(
                    "categorize_expenses:submitted_page page_index=%d base=%d end=%d future_id=%s",
                    k,
                    base,
                    end,
                    id(future),
                )

            logger.info("categorize_expenses:all_pages_submitted futures_count=%d", len(futures))

            # Process completed futures
            completed_count = 0
            start_time = time.perf_counter()

            for fut in as_completed(futures):
                completed_count += 1
                elapsed_time = time.perf_counter() - start_time

                logger.info(
                    "categorize_expenses:future_completed completed=%d/%d elapsed_sec=%.2f "
                    "future_id=%s",
                    completed_count,
                    len(futures),
                    elapsed_time,
                    id(fut),
                )

                try:
                    page_index, base, page_categories = fut.result()
                    logger.debug(
                        "categorize_expenses:processing_result page_index=%d base=%d "
                        "categories_count=%d",
                        page_index,
                        base,
                        len(page_categories),
                    )

                    for i, cat in enumerate(page_categories):
                        categories_by_abs_idx[base + i] = cat

                except Exception as e:
                    logger.error(
                        "categorize_expenses:future_failed future_id=%s error=%s error_type=%s",
                        id(fut),
                        str(e),
                        e.__class__.__name__,
                    )
                    raise

            total_time = time.perf_counter() - start_time
            logger.info("categorize_expenses:all_pages_completed total_time_sec=%.2f", total_time)

        except Exception as e:
            logger.error(
                "categorize_expenses:pool_exception error=%s error_type=%s futures_count=%d",
                str(e),
                e.__class__.__name__,
                len(futures),
            )

            # Cancel any remaining futures
            cancelled_count = 0
            for f in futures:
                try:
                    if not f.done():
                        f.cancel()
                        cancelled_count += 1
                        logger.debug("categorize_expenses:cancelled_future future_id=%s", id(f))
                except Exception as cancel_e:
                    logger.warning(
                        "categorize_expenses:cancel_failed future_id=%s error=%s",
                        id(f),
                        str(cancel_e),
                    )

            logger.info(
                "categorize_expenses:cancellation_complete cancelled_count=%d", cancelled_count
            )
            raise

    # Defensive check.
    missing = [i for i, v in enumerate(categories_by_abs_idx) if v is None]
    if missing:  # pragma: no cover - defensive
        raise RuntimeError(f"Internal error: missing categories at indices {missing}")

    results: list[CategorizedTransaction] = []
    for i in range(n_total):
        category: str = cast(str, categories_by_abs_idx[i])
        results.append(CategorizedTransaction(transaction=original_seq[i], category=category))
    return results


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
