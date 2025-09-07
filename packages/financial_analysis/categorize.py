"""Expense categorization flow extracted from ``api.py``.

Public API:
    - :func:`categorize_expenses`

All other helpers, constants, and implementation details are private to this
module. No side effects occur at import time (no client creation, no logging
handler attachment, no environment reads).
"""

from __future__ import annotations

import json
import math
import random
import time
from collections.abc import Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any, cast

from openai import OpenAI
from openai.types.responses import ResponseTextConfigParam

from . import prompting
from .categorization import (
    ALLOWED_CATEGORIES,
    ensure_valid_ctv_descriptions,
    parse_and_align_categories,
)
from .logging_setup import get_logger
from .models import CategorizedTransaction, Transactions

# ---- Tunables (private) ------------------------------------------------------

_PAGE_SIZE_DEFAULT: int = 100
_CONCURRENCY: int = 4
_MAX_ATTEMPTS: int = 3
_BACKOFF_SCHEDULE_SEC: tuple[float, ...] = (0.5, 2.0)
_JITTER_PCT: float = 0.20


_logger = get_logger("financial_analysis.categorize")


# ---- Internal helpers --------------------------------------------------------


def _extract_response_json_mapping(resp: Any) -> Mapping[str, Any]:
    """Decode the JSON mapping from an OpenAI Responses SDK result.

    Behavior matches the prior implementation in ``api.py``:
    - Prefer ``resp.output_text``; fallback to ``resp.output[0].content[0].text``.
    - Raise ``ValueError`` if text cannot be located or if JSON decoding fails.
    """

    text: str | None = getattr(resp, "output_text", None)
    if not text:
        try:
            first = resp.output[0] if getattr(resp, "output", None) else None
            content = getattr(first, "content", None)
            if content and len(content) > 0:
                maybe_text = getattr(content[0], "text", None)
                if isinstance(maybe_text, str):
                    text = maybe_text
        except Exception:  # noqa: BLE001 - tolerate SDK shape differences
            text = None
    if not text or not isinstance(text, str):
        raise ValueError("Unexpected Responses API shape; unable to locate text output")

    try:
        decoded: Mapping[str, Any] = json.loads(text)
    except json.JSONDecodeError as e:  # pragma: no cover - defensive path
        raise ValueError("Model output was not valid JSON per the requested schema") from e
    return decoded


def _validate_and_materialize(transactions: Transactions) -> list[Mapping[str, Any]]:
    # Materialize exactly once; validate and reuse the same list.
    _materialized = list(transactions)
    if not all(isinstance(item, Mapping) for item in _materialized):
        raise TypeError(
            "categorize_expenses expects each transaction to be a mapping (CTV) with keys "
            "like 'id', 'description', 'amount', 'date', 'merchant', 'memo'."
        )
    original_seq: list[Mapping[str, Any]] = _materialized

    # Validate descriptions early (fail-fast)
    to_validate: list[dict[str, Any]] = []
    for idx, record in enumerate(original_seq):
        to_validate.append(
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
    ensure_valid_ctv_descriptions(to_validate)
    return original_seq


def _paginate(n_total: int, page_size: int) -> Iterable[tuple[int, int, int]]:
    pages_total = math.ceil(n_total / page_size)
    for k in range(pages_total):
        base = k * page_size
        end = min(base + page_size, n_total)
        yield (k, base, end)


def _build_page_payload(
    original_seq: list[Mapping[str, Any]],
    base: int,
    end: int,
) -> tuple[list[dict[str, Any]], str]:
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
    return ctv_page, user_content


def _create_client() -> OpenAI:
    return OpenAI()


def _is_retryable(exc: BaseException) -> bool:
    sc = getattr(exc, "status_code", None)
    if isinstance(sc, int) and (sc == 429 or 500 <= sc < 600):
        return True
    if isinstance(exc, ValueError):  # parse_and_align / JSON decode
        return True
    return False


def _sleep_backoff(attempt_no: int) -> None:
    if attempt_no - 1 < len(_BACKOFF_SCHEDULE_SEC):
        base = _BACKOFF_SCHEDULE_SEC[attempt_no - 1]
    else:
        base = _BACKOFF_SCHEDULE_SEC[-1]
    jitter = base * _JITTER_PCT
    delay = base + random.uniform(-jitter, jitter)
    time.sleep(max(0.0, delay))


def _categorize_page(
    page_index: int,
    *,
    base: int,
    end: int,
    original_seq: list[Mapping[str, Any]],
    system_instructions: str,
    text_cfg: ResponseTextConfigParam,
) -> tuple[int, int, list[str]]:
    count = end - base
    _logger.info(
        "categorize_expenses:page_start page_index=%d base=%d end=%d count=%d",
        page_index,
        base,
        end,
        count,
    )

    ctv_page, user_content = _build_page_payload(original_seq, base, end)
    _logger.debug(
        "categorize_expenses:page_prepared page_index=%d ctv_count=%d content_length=%d",
        page_index,
        len(ctv_page),
        len(user_content),
    )

    # Instantiate the client once per page and reuse across retries.
    client = _create_client()
    attempt = 1
    while True:
        t0 = time.perf_counter()
        try:
            _logger.info(
                (
                    "categorize_expenses:page_attempt page_index=%d base=%d count=%d "
                    "attempt=%d max=%d"
                ),
                page_index,
                base,
                count,
                attempt,
                _MAX_ATTEMPTS,
            )
            resp = client.responses.create(
                model="gpt-5",
                instructions=system_instructions,
                input=user_content,
                text=text_cfg,
            )
            decoded = _extract_response_json_mapping(resp)
            page_categories = parse_and_align_categories(decoded, num_items=count)
            dt_ms = (time.perf_counter() - t0) * 1000.0
            _logger.info(
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
            _logger.info(
                "categorize_expenses:page_complete page_index=%d categories_returned=%d",
                page_index,
                len(page_categories),
            )
            return (page_index, base, page_categories)
        except Exception as e:  # noqa: BLE001
            dt_ms = (time.perf_counter() - t0) * 1000.0
            if attempt >= _MAX_ATTEMPTS or not _is_retryable(e):
                _logger.error(
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
                if isinstance(e, ValueError):
                    raise e
                raise RuntimeError(
                    f"categorize_expenses failed for page {page_index} "
                    f"(base={base}, count={count}): {e}"
                ) from e
            _logger.warning(
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
            _sleep_backoff(attempt)
            attempt += 1


# ---- Public API --------------------------------------------------------------


def categorize_expenses(
    transactions: Transactions,
    *,
    page_size: int = _PAGE_SIZE_DEFAULT,
) -> Iterable[CategorizedTransaction]:
    """Categorize expenses via OpenAI Responses API (model: ``gpt-5``).

    Preserves exact behavior, outputs, and error semantics from the previous
    implementation in ``api.py``.
    """

    _logger.info("categorize_expenses:function_start page_size=%d", page_size)

    original_seq = _validate_and_materialize(transactions)
    n_total = len(original_seq)

    if n_total == 0:
        return []
    if not isinstance(page_size, int) or page_size <= 0:
        raise ValueError("page_size must be a positive integer")

    pages_total = math.ceil(n_total / page_size)
    _logger.info(
        "categorize_expenses:start pages_total=%d total_items=%d page_size=%d concurrency=%d",
        pages_total,
        n_total,
        page_size,
        _CONCURRENCY,
    )

    # Static per-call components reused across pages
    system_instructions = prompting.build_system_instructions()
    response_format = prompting.build_response_format(ALLOWED_CATEGORIES)
    text_cfg: ResponseTextConfigParam = cast(ResponseTextConfigParam, {"format": response_format})

    categories_by_abs_idx: list[str | None] = [None] * n_total

    futures: list[Future[tuple[int, int, list[str]]]] = []
    _logger.info(
        "categorize_expenses:submitting_pages pages_total=%d concurrency=%d",
        pages_total,
        _CONCURRENCY,
    )

    with ThreadPoolExecutor(max_workers=_CONCURRENCY) as pool:
        try:
            for page_index, base, end in _paginate(n_total, page_size):
                fut = pool.submit(
                    _categorize_page,
                    page_index,
                    base=base,
                    end=end,
                    original_seq=original_seq,
                    system_instructions=system_instructions,
                    text_cfg=text_cfg,
                )
                futures.append(fut)
                _logger.debug(
                    "categorize_expenses:submitted_page page_index=%d base=%d end=%d future_id=%s",
                    page_index,
                    base,
                    end,
                    id(fut),
                )

            _logger.info("categorize_expenses:all_pages_submitted futures_count=%d", len(futures))

            completed_count = 0
            start_time = time.perf_counter()

            for fut in as_completed(futures):
                completed_count += 1
                elapsed_time = time.perf_counter() - start_time
                _logger.info(
                    (
                        "categorize_expenses:future_completed completed=%d/%d "
                        "elapsed_sec=%.2f future_id=%s"
                    ),
                    completed_count,
                    len(futures),
                    elapsed_time,
                    id(fut),
                )

                try:
                    page_index, base, page_categories = fut.result()
                    _logger.debug(
                        (
                            "categorize_expenses:processing_result page_index=%d "
                            "base=%d categories_count=%d"
                        ),
                        page_index,
                        base,
                        len(page_categories),
                    )
                    for i, cat in enumerate(page_categories):
                        categories_by_abs_idx[base + i] = cat
                except Exception as e:
                    _logger.error(
                        "categorize_expenses:future_failed future_id=%s error=%s error_type=%s",
                        id(fut),
                        str(e),
                        e.__class__.__name__,
                    )
                    raise

            total_time = time.perf_counter() - start_time
            _logger.info("categorize_expenses:all_pages_completed total_time_sec=%.2f", total_time)

        except Exception as e:
            _logger.error(
                "categorize_expenses:pool_exception error=%s error_type=%s futures_count=%d",
                str(e),
                e.__class__.__name__,
                len(futures),
            )

            cancelled_count = 0
            for f in futures:
                try:
                    if not f.done():
                        f.cancel()
                        cancelled_count += 1
                        _logger.debug("categorize_expenses:cancelled_future future_id=%s", id(f))
                except Exception as cancel_e:  # pragma: no cover - defensive
                    _logger.warning(
                        "categorize_expenses:cancel_failed future_id=%s error=%s",
                        id(f),
                        str(cancel_e),
                    )
            _logger.info(
                "categorize_expenses:cancellation_complete cancelled_count=%d",
                cancelled_count,
            )
            # Proactively shut down the pool to avoid waiting on not-yet-started tasks.
            try:
                pool.shutdown(cancel_futures=True)
            except Exception:  # pragma: no cover - defensive
                pass
            raise

    missing = [i for i, v in enumerate(categories_by_abs_idx) if v is None]
    if missing:  # pragma: no cover - defensive
        raise RuntimeError(f"Internal error: missing categories at indices {missing}")

    results: list[CategorizedTransaction] = []
    for i in range(n_total):
        category: str = cast(str, categories_by_abs_idx[i])
        results.append(CategorizedTransaction(transaction=original_seq[i], category=category))
    return results
