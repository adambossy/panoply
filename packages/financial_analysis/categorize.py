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
from typing import Any, NamedTuple, cast

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

# Centralized model name for Responses API calls
_MODEL: str = "gpt-5"


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
                txt_obj = getattr(content[0], "text", None)
                if isinstance(txt_obj, str):
                    text = txt_obj
                else:
                    # Some SDKs expose text as an object with a ``value`` string.
                    maybe_val = getattr(txt_obj, "value", None)
                    if isinstance(maybe_val, str):
                        text = maybe_val
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
    """Yield page tuples ``(page_index, base, end)`` using half-open ranges.

    Contract:
    - Ranges are half-open: ``[base, end)`` with ``0 <= base < end <= n_total``.
    - ``page_index`` is 0-based and increases monotonically.
    - Consumers should treat any per-item ``idx`` as page-relative (0..count-1)
      and align back to absolute indices via ``base + idx``.
    """

    pages_total = math.ceil(n_total / page_size)
    for k in range(pages_total):
        base = k * page_size
        end = min(base + page_size, n_total)
        yield (k, base, end)


def _build_page_payload(
    original_seq: list[Mapping[str, Any]],
    base: int,
    end: int,
) -> tuple[int, str]:
    """Return ``(count, user_content)`` for a page slice ``[base, end)``.

    Notes:
    - Page-relative indices are emitted as ``idx`` starting at 0 and are used

      later to align results back to absolute positions.
    - The caller does not need the full CTV list; only the count is used for
      alignment checks and logging.
    """

    ctv_page: list[dict[str, Any]] = []
    for page_idx, record in enumerate(original_seq[base:end]):
        ctv_page.append(
            {
                "idx": page_idx,  # page-relative index (0..count-1)
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
    return len(ctv_page), user_content


def _create_client() -> OpenAI:
    return OpenAI()


def _is_retryable(exc: BaseException) -> bool:
    """Return True only for HTTP 429 and 5xx errors.

    Narrowed per owner confirmation: parsing/validation errors (e.g.,
    ``ValueError`` from JSON decode or schema alignment) are terminal and must
    not be retried.
    """

    sc = getattr(exc, "status_code", None)
    if isinstance(sc, int) and (sc == 429 or 500 <= sc < 600):
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


class PageResult(NamedTuple):
    page_index: int
    base: int
    categories: list[str]


def _categorize_page(
    page_index: int,
    *,
    base: int,
    end: int,
    original_seq: list[Mapping[str, Any]],
    system_instructions: str,
    text_cfg: ResponseTextConfigParam,
) -> PageResult:
    count, user_content = _build_page_payload(original_seq, base, end)
    _logger.debug(
        "categorize_expenses:page_prepared page_index=%d ctv_count=%d content_length=%d",
        page_index,
        count,
        len(user_content),
    )

    # Instantiate the client once per page and reuse across retries.
    client = _create_client()
    attempt = 1
    while True:
        t0 = time.perf_counter()
        try:
            _logger.debug(
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
                model=_MODEL,
                instructions=system_instructions,
                input=user_content,
                text=text_cfg,
            )
            decoded = _extract_response_json_mapping(resp)
            page_categories = parse_and_align_categories(decoded, num_items=count)
            dt_ms = (time.perf_counter() - t0) * 1000.0
            _logger.debug(
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
            return PageResult(page_index=page_index, base=base, categories=page_categories)
        except Exception as e:  # noqa: BLE001
            dt_ms = (time.perf_counter() - t0) * 1000.0
            # Retry scope narrowed to 429/5xx only.
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
                    # Parsing/validation failures are terminal (no retries)
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

    Behavior notes:
    - If ``transactions`` is empty, this function returns ``[]`` without
      validating ``page_size`` (historical contract, preserved).
    - Otherwise ``page_size`` must be a positive integer.
    """

    _logger.debug("categorize_expenses:function_start page_size=%d", page_size)

    original_seq = _validate_and_materialize(transactions)
    n_total = len(original_seq)

    if n_total == 0:
        return []
    if not isinstance(page_size, int) or page_size <= 0:
        raise ValueError("page_size must be a positive integer")

    pages_total = math.ceil(n_total / page_size)
    _logger.debug(
        "categorize_expenses:start pages_total=%d total_items=%d page_size=%d concurrency=%d",
        pages_total,
        n_total,
        page_size,
        _CONCURRENCY,
    )

    # Static per-call components reused across pages
    system_instructions = prompting.build_system_instructions()
    response_format = prompting.build_response_format(ALLOWED_CATEGORIES)
    # The OpenAI client accepts a plain dict for ``text``; this cast is for typing only.
    text_cfg: ResponseTextConfigParam = cast(ResponseTextConfigParam, {"format": response_format})

    categories_by_abs_idx: list[str | None] = [None] * n_total

    futures: list[Future[PageResult]] = []
    _logger.debug(
        "categorize_expenses:submitting_pages pages_total=%d concurrency=%d",
        pages_total,
        _CONCURRENCY,
    )

    # Simplified executor lifecycle with context manager; cancel futures on error.
    try:
        with ThreadPoolExecutor(max_workers=_CONCURRENCY) as pool:
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

            _logger.debug("categorize_expenses:all_pages_submitted futures_count=%d", len(futures))

            start_time = time.perf_counter()
            for fut in as_completed(futures):
                try:
                    result = fut.result()
                    _logger.debug(
                        (
                            "categorize_expenses:processing_result page_index=%d "
                            "base=%d categories_count=%d"
                        ),
                        result.page_index,
                        result.base,
                        len(result.categories),
                    )
                    for i, cat in enumerate(result.categories):
                        categories_by_abs_idx[result.base + i] = cat
                except Exception as e:
                    _logger.error(
                        "categorize_expenses:future_failed future_id=%s error=%s error_type=%s",
                        id(fut),
                        str(e),
                        e.__class__.__name__,
                    )
                    # Cancel remaining work and propagate the error
                    pool.shutdown(wait=False, cancel_futures=True)
                    raise

            total_time = time.perf_counter() - start_time
            _logger.debug("categorize_expenses:all_pages_completed total_time_sec=%.2f", total_time)
    except Exception as e:
        _logger.error(
            "categorize_expenses:pool_exception error=%s error_type=%s futures_count=%d",
            str(e),
            e.__class__.__name__,
            len(futures),
        )
        raise

    missing = [i for i, v in enumerate(categories_by_abs_idx) if v is None]
    if missing:  # pragma: no cover - defensive
        raise RuntimeError(f"Internal error: missing categories at indices {missing}")

    results: list[CategorizedTransaction] = []
    for i in range(n_total):
        category: str = cast(str, categories_by_abs_idx[i])
        results.append(CategorizedTransaction(transaction=original_seq[i], category=category))
    return results
