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
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, NamedTuple, cast

from openai import OpenAI
from openai.types.responses import ResponseTextConfigParam
from pmap import p_map

from . import prompting
from .categorization import (
    ensure_valid_ctv_descriptions,
    parse_and_align_category_details,
)
from .logging_setup import get_logger
from .models import CategorizedTransaction, LLMCategoryDetails, Transactions

# ---- Tunables (private) ------------------------------------------------------

_PAGE_SIZE_DEFAULT: int = 10
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
    exemplar_abs_indices: list[int],
    *,
    taxonomy: Sequence[Mapping[str, Any]],
) -> tuple[int, str]:
    """Return ``(count, user_content)`` for the given exemplar indices.

    Notes:
    - The page consists only of exemplar transactions selected from the
      original sequence by absolute index. Items are reindexed to
      page-relative ``idx`` values (0..count-1) for alignment with model
      output.
    - The caller does not need the full CTV list; only the count is used for
      alignment checks and logging.
    """

    ctv_page: list[dict[str, Any]] = []
    for page_idx, abs_i in enumerate(exemplar_abs_indices):
        record = original_seq[abs_i]
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
    # Thread taxonomy context; prompt hides the flat list when taxonomy is present.
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
    # List of (group_root_abs_index, parsed_result_dict)
    results: list[tuple[int, dict[str, Any]]]


def _categorize_page(
    page_index: int,
    *,
    exemplar_abs_indices: list[int],  # absolute indices into original_seq
    original_seq: list[Mapping[str, Any]],
    system_instructions: str,
    text_cfg: ResponseTextConfigParam,
    taxonomy: Sequence[Mapping[str, Any]],
) -> PageResult:
    # Build the page payload from exemplars only; keep page-relative idx
    count, user_content = _build_page_payload(original_seq, exemplar_abs_indices, taxonomy=taxonomy)

    # Derive strict allow-list from taxonomy (dedupe, drop blanks) once per page
    allowed: tuple[str, ...] = tuple(
        dict.fromkeys(
            c
            for c in (
                (str(d.get("code") or "").strip()) for d in taxonomy if isinstance(d, Mapping)
            )
            if c
        )
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
                tools=[{"type": "web_search"}],
                tool_choice="auto",
            )
            decoded = _extract_response_json_mapping(resp)
            detailed = parse_and_align_category_details(
                decoded, num_items=count, allowed_categories=allowed
            )
            # Map page-relative results back to absolute exemplar indices
            out: list[tuple[int, dict[str, Any]]] = []
            for page_idx, item in enumerate(detailed):
                abs_index = exemplar_abs_indices[page_idx]
                out.append((abs_index, item))
            return PageResult(page_index=page_index, results=out)
        except Exception as e:  # noqa: BLE001
            dt_ms = (time.perf_counter() - t0) * 1000.0
            # Retry scope narrowed to 429/5xx only.
            if attempt >= _MAX_ATTEMPTS or not _is_retryable(e):
                _logger.error(
                    (
                        "categorize_expenses:page_failed_terminal page_index=%d exemplars=%d "
                        "latency_ms=%.2f error=%s"
                    ),
                    page_index,
                    count,
                    dt_ms,
                    e.__class__.__name__,
                )
                if isinstance(e, ValueError):
                    # Parsing/validation failures are terminal (no retries)
                    raise e
                raise RuntimeError(
                    f"categorize_expenses failed for page {page_index} (exemplars={count}): {e}"
                ) from e
            _logger.warning(
                (
                    "categorize_expenses:page_retry page_index=%d count=%d "
                    "latency_ms=%.2f error=%s attempt=%d"
                ),
                page_index,
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
    taxonomy: Sequence[Mapping[str, Any]],
    *,
    page_size: int = _PAGE_SIZE_DEFAULT,
) -> Iterable[CategorizedTransaction]:
    """Categorize expenses via the OpenAI Responses API (model: ``gpt-5``).

    Parameters
    ----------
    transactions:
        CTV items (mappings with keys like ``id``, ``description``, ``amount``,
        ``date``, ``merchant``, ``memo``) to categorize.
    taxonomy:
        Required two‑level taxonomy (sequence of mappings with at least
        ``code`` and ``parent_code`` keys). Used to build both the JSON Schema
        enum and a concise hierarchy section in the prompt so the model prefers
        specific child categories and otherwise falls back to parents.
    page_size:
        Page size for batching requests (default 100). Must be a positive
        integer when ``transactions`` is not empty.

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

    # Group before LLM: normalize merchant/description; pick one exemplar per group
    def _norm_merchant_key(tx: Mapping[str, Any]) -> str | None:
        raw = tx.get("merchant") or tx.get("description")
        if raw is None:
            return None
        s = unicodedata.normalize("NFKC", str(raw)).strip()
        if not s:
            return None
        return " ".join(s.split()).casefold()

    by_key: dict[str, list[int]] = {}
    singleton_indices: list[int] = []
    for i, tx in enumerate(original_seq):
        k = _norm_merchant_key(tx)
        if k is None:
            singleton_indices.append(i)
        else:
            by_key.setdefault(k, []).append(i)
    # Deterministic exemplar per group: the smallest absolute index
    exemplars: list[int] = []
    for idxs in by_key.values():
        exemplars.append(min(idxs))
    exemplars.extend(singleton_indices)  # singletons act as their own group
    exemplars.sort()

    n_groups = len(exemplars)

    # Static per-call components reused across pages
    system_instructions = prompting.build_system_instructions()

    # Build response schema from taxonomy
    response_format = prompting.build_response_format(taxonomy)
    text_cfg = ResponseTextConfigParam(
        format=response_format,
    )

    # Hold per-group parsed details keyed by exemplar absolute index
    group_details_by_exemplar: dict[int, dict[str, Any]] = {}

    try:
        # Build pages over exemplars
        pages: list[list[int]] = []
        for _, base, end in _paginate(n_groups, page_size):
            pages.append(exemplars[base:end])

        def _map_page(page_index_and_indices: tuple[int, list[int]]) -> PageResult:
            page_index, indices = page_index_and_indices
            try:
                return _categorize_page(
                    page_index,
                    exemplar_abs_indices=indices,
                    original_seq=original_seq,
                    system_instructions=system_instructions,
                    text_cfg=text_cfg,
                    taxonomy=taxonomy,
                )
            except Exception as e:  # noqa: BLE001
                if isinstance(e, ValueError):
                    raise
                raise RuntimeError(f"categorize_expenses failed for page_index={page_index}") from e

        page_inputs: list[tuple[int, list[int]]] = [(i, pg) for i, pg in enumerate(pages)]
        page_results: list[PageResult] = p_map(
            page_inputs, _map_page, concurrency=_CONCURRENCY, stop_on_error=True
        )
        for page in page_results:
            for exemplar_abs_idx, item in page.results:
                group_details_by_exemplar[exemplar_abs_idx] = item
    except Exception as e:
        _logger.error(
            "categorize_expenses:pmap_exception error=%s error_type=%s",
            str(e),
            e.__class__.__name__,
        )
        raise

    # Fan out group-level decisions to all members
    results: list[CategorizedTransaction] = []
    # Precompute mapping from exemplar -> member indices (including itself)
    members_by_exemplar: dict[int, list[int]] = {ex: [] for ex in exemplars}
    for idxs in by_key.values():
        root = min(idxs)
        members_by_exemplar[root].extend(idxs)
    for i in singleton_indices:
        members_by_exemplar[i].append(i)

    # Fill results with defaults to preserve order, then set via groups
    results = [CategorizedTransaction(transaction=tx, category="Unknown") for tx in original_seq]

    for exemplar_abs_idx, members in members_by_exemplar.items():
        details = group_details_by_exemplar.get(exemplar_abs_idx)
        if details is None:  # pragma: no cover - defensive
            # Should not happen; treat as Unknown
            cat_effective = "Unknown"
            llm_details = None
        else:
            cat = cast(str, details.get("category"))
            revised_cat = details.get("revised_category")
            cat_effective = cast(str, (revised_cat or cat))
            llm_details = LLMCategoryDetails(
                rationale=cast(str | None, details.get("rationale")),
                score=cast(float | None, details.get("score")),
                revised_category=cast(str | None, details.get("revised_category")),
                revised_rationale=cast(str | None, details.get("revised_rationale")),
                revised_score=cast(float | None, details.get("revised_score")),
                citations=tuple(details.get("citations") or []) or None,
            )
        for m in members:
            results[m] = CategorizedTransaction(
                transaction=original_seq[m], category=cat_effective, llm=llm_details
            )

    return results
