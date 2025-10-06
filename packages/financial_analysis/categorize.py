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
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, NamedTuple, cast

from openai import OpenAI
from openai.types.responses import ResponseTextConfigParam
from pmap import p_map

from . import prompting
from .categorization import ensure_valid_ctv_descriptions, parse_and_align_categories
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
    *,
    taxonomy: Sequence[Mapping[str, Any]] | None,
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
    # Thread only the taxonomy context; the flat allow‑list is not rendered.
    user_content = prompting.build_user_content(ctv_json, taxonomy=taxonomy)
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
    allowed_categories: tuple[str, ...],
    taxonomy: Sequence[Mapping[str, Any]] | None,
) -> PageResult:
    count, user_content = _build_page_payload(
        original_seq,
        base,
        end,
        taxonomy=taxonomy,
    )

    # Instantiate the client once per page and reuse across retries.
    client = _create_client()
    attempt = 1
    while True:
        t0 = time.perf_counter()
        try:
            resp = client.responses.create(
                model=_MODEL,
                instructions=system_instructions,
                input=user_content,
                text=text_cfg,
            )
            decoded = _extract_response_json_mapping(resp)
            page_categories = parse_and_align_categories(
                decoded, num_items=count, allowed_categories=allowed_categories
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
    allowed_categories: Iterable[str] | None = None,
    taxonomy: Sequence[Mapping[str, Any]] | None = None,
    # Back-compat alias: prefer ``taxonomy`` when both are provided.
    taxonomy_hierarchy: Sequence[Mapping[str, Any]] | None = None,
) -> Iterable[CategorizedTransaction]:
    """Categorize expenses via the OpenAI Responses API (model: ``gpt-5``).

    Parameters
    ----------
    transactions:
        CTV items (mappings with keys like ``id``, ``description``, ``amount``,
        ``date``, ``merchant``, ``memo``) to categorize.
    page_size:
        Page size for batching requests (default 100). Must be a positive
        integer when ``transactions`` is not empty.
    allowed_categories:
        Required flat allow‑list of category codes (parents and children). The
        model's output is validated against this set. When an invalid category
        is returned and a fallback is permitted by the parser, it will fall
        back to ``"Other"`` or ``"Unknown"`` only if present in this list.
    taxonomy_hierarchy:
        Optional two‑level taxonomy (sequence of mappings with at least
        ``code`` and ``parent_code`` keys). Used to render a concise hierarchy
        section in the prompt so the model prefers specific child categories
        and otherwise falls back to parents.

    Returns
    -------
    Iterable[CategorizedTransaction]
        One result per input item, in the same order.

    Notes
    -----
    - If ``transactions`` is empty, this function returns ``[]`` without
      validating ``page_size`` (historical contract, preserved).
    """

    # Progress logging intentionally omitted.

    original_seq = _validate_and_materialize(transactions)
    n_total = len(original_seq)

    if n_total == 0:
        return []
    if not isinstance(page_size, int) or page_size <= 0:
        raise ValueError("page_size must be a positive integer")

    # Determine pages lazily via _paginate(); no need to precompute total count.

    # Static per-call components reused across pages
    system_instructions = prompting.build_system_instructions()
    # Prefer the new ``taxonomy`` name; accept the legacy ``taxonomy_hierarchy`` as alias.
    if taxonomy is None and taxonomy_hierarchy is not None:
        taxonomy = taxonomy_hierarchy

    # Resolve the effective allowed categories once per call and thread through
    # response_format and result validation (not rendered in the prompt).
    _allowed: tuple[str, ...]
    if allowed_categories is None:
        # Derive from taxonomy when no explicit allow-list is provided.
        if taxonomy is None:
            raise ValueError(
                "Either allowed_categories or taxonomy must be provided to categorize_expenses"
            )
        _norm = [
            str(d.get("code") or "").strip() for d in taxonomy if isinstance(d, Mapping)
        ]
        _norm = [c for c in _norm if c]
        _allowed = tuple(dict.fromkeys(_norm))
        if not _allowed:
            raise ValueError("taxonomy produced an empty set of category codes")
    else:
        # Normalize and validate allowed categories (strip, drop blanks, dedupe preserving order)
        _norm = [
            c.strip() for c in allowed_categories if isinstance(c, str) and c.strip()
        ]
        _allowed = tuple(dict.fromkeys(_norm))
        if not _allowed:
            raise ValueError(
                "allowed_categories must be a non-empty iterable of non-blank strings"
            )
    response_format = prompting.build_response_format(_allowed)
    # The OpenAI client accepts a plain dict for ``text``; this cast is for typing only.
    text_cfg: ResponseTextConfigParam = cast(ResponseTextConfigParam, {"format": response_format})

    categories_by_abs_idx: list[str | None] = [None] * n_total

    try:
        pages_iter = _paginate(n_total, page_size)

        def _map_page(t: tuple[int, int, int]) -> PageResult:
            page_index, base, end = t
            try:
                return _categorize_page(
                    page_index,
                    base=base,
                    end=end,
                    original_seq=original_seq,
                    system_instructions=system_instructions,
                    text_cfg=text_cfg,
                    allowed_categories=_allowed,
                    taxonomy=taxonomy,
                )
            except Exception as e:  # noqa: BLE001
                # Preserve ValueError semantics for validation/parse errors.
                if isinstance(e, ValueError):
                    raise
                raise RuntimeError(
                    f"categorize_expenses failed for page_index={page_index} base={base} end={end}"
                ) from e

        page_results: list[PageResult] = p_map(
            pages_iter, _map_page, concurrency=_CONCURRENCY, stop_on_error=True
        )
        for page in page_results:
            for i, cat in enumerate(page.categories):
                categories_by_abs_idx[page.base + i] = cat
    except Exception as e:
        _logger.error(
            "categorize_expenses:pmap_exception error=%s error_type=%s",
            str(e),
            e.__class__.__name__,
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
