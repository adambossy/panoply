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
from .cache import compute_dataset_id, read_page_from_cache, write_page_to_cache
from .categorization import (
    ensure_valid_ctv_descriptions,
    parse_and_align_category_details,
)
from .logging_setup import get_logger
from .models import CategorizedTransaction, LlmDecision, Transactions

# DB/session and review helpers are imported lazily inside functions where
# needed to avoid side effects at import time and to limit dependency surface.

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
    # List of (group_root_abs_index, typed_decision)
    results: list[tuple[int, LlmDecision]]


def _categorize_page(
    page_index: int,
    *,
    dataset_id: str,
    page_size: int,
    exemplar_abs_indices: list[int],  # absolute indices into original_seq
    original_seq: list[Mapping[str, Any]],
    system_instructions: str,
    text_cfg: ResponseTextConfigParam,
    taxonomy: Sequence[Mapping[str, Any]],
    source_provider: str = "amex",
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

    cached = read_page_from_cache(
        dataset_id=dataset_id,
        page_size=page_size,
        page_index=page_index,
        source_provider=source_provider,
        taxonomy=taxonomy,
        original_seq=original_seq,
        exemplar_abs_indices=exemplar_abs_indices,
    )
    if cached is not None:
        # Visible signal for cache hit (kept concise and structured for grep/parse)
        _logger.info(
            "categorize_expenses:page_cache_hit page_index=%d num_transactions=%d",
            page_index,
            len(cached),
        )
        return PageResult(page_index=page_index, results=cached)

    # Instantiate the client once per page and reuse across retries.
    # Visible trace that this page will be sent to the model (cache miss path).
    # Keep a concise, structured message so downstream log processors can key on it.
    _logger.info(
        "categorize_expenses:page_llm page_index=%d num_transactions=%d",
        page_index,
        count,
    )

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
            out: list[tuple[int, LlmDecision]] = []
            for page_idx, item in enumerate(detailed):
                abs_index = exemplar_abs_indices[page_idx]
                out.append((abs_index, LlmDecision.model_validate(item)))
            write_page_to_cache(
                dataset_id=dataset_id,
                page_size=page_size,
                page_index=page_index,
                source_provider=source_provider,
                taxonomy=taxonomy,
                original_seq=original_seq,
                exemplar_abs_indices=exemplar_abs_indices,
                items=out,
            )
            # Completion signal for successful model call on this page (cache miss path)
            dt_ms = (time.perf_counter() - t0) * 1000.0
            _logger.info(
                "categorize_expenses:page_done page_index=%d num_transactions=%d latency_ms=%.2f",
                page_index,
                len(out),
                dt_ms,
            )
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


def _normalize_merchant_key(tx: Mapping[str, Any]) -> str | None:
    """Return a normalized grouping key from ``merchant`` or ``description``.

    - Normalizes to NFKC, collapses internal whitespace, strips, and casefolds.
    - Returns ``None`` when no usable value is present (treated as singleton).
    """

    raw = tx.get("merchant") or tx.get("description")
    if raw is None:
        return None
    s = unicodedata.normalize("NFKC", str(raw)).strip()
    if not s:
        return None
    return " ".join(s.split()).casefold()


def _group_by_normalized_merchant(
    original_seq: list[Mapping[str, Any]],
) -> tuple[list[int], dict[str, list[int]], list[int]]:
    """Group transactions by normalized merchant/description and pick exemplars.

    Returns a tuple ``(exemplars, by_key, singleton_indices)`` where:
    - ``exemplars`` is a sorted list of absolute indices (smallest index per group
      plus singletons).
    - ``by_key`` maps a normalized key to the absolute indices in that group.
    - ``singleton_indices`` are items with no usable key (treated as their own group).
    """

    by_key: dict[str, list[int]] = {}
    singleton_indices: list[int] = []
    for i, tx in enumerate(original_seq):
        k = _normalize_merchant_key(tx)
        if k is None:
            singleton_indices.append(i)
        else:
            by_key.setdefault(k, []).append(i)

    exemplars: list[int] = []
    for idxs in by_key.values():
        exemplars.append(min(idxs))
    exemplars.extend(singleton_indices)  # singletons act as their own group
    exemplars.sort()

    return exemplars, by_key, singleton_indices


def prefill_unanimous_groups_from_db(
    ctv_items: list[Mapping[str, Any]],
    *,
    database_url: str | None,
    source_provider: str,
    source_account: str | None,
) -> tuple[set[int], int]:
    """Auto-assign unanimous DB categories per group and persist them.

    Groups transactions by normalized merchant, queries duplicates in the DB
    within the given ``(source_provider, source_account)`` scope, and when all
    non-null categories agree for a group, persists that category for all
    positions in the group. Returns a tuple of ``(prefilled_positions,
    prefilled_groups)``.

    Raises a ``RuntimeError`` with context on grouping failures; DB and
    persistence errors are propagated as-is to the caller.
    """

    # Local imports keep module import cheap and avoid global DB dependencies
    from db.client import session_scope

    from .duplicates import PreparedItem, persist_group, query_group_duplicates
    from .persistence import compute_fingerprint

    try:
        _exemplars, by_key, _singletons = _group_by_normalized_merchant(ctv_items)
    except Exception as e:  # pragma: no cover - defensive clarity
        raise RuntimeError(f"failed to group transactions: {e}") from e

    prefilled_positions: set[int] = set()
    prefilled_groups = 0

    # Emit a concise start line with group counts to help operators trace work
    _logger.info(
        "prefill:start groups=%d singletons=%d",
        len(by_key),
        len(_singletons),
    )

    with session_scope(database_url=database_url) as session:
        for key, positions in by_key.items():
            if not positions:
                continue

            # Build identifiers for DB lookup
            group_eids: list[str] = []
            group_fps: list[str] = []
            group_items: list[PreparedItem] = []
            for i in positions:
                tx = ctv_items[i]
                tx_id_val = tx.get("id")
                eid = str(tx_id_val).strip() if tx_id_val is not None else None
                if eid:
                    group_eids.append(eid)
                fp = compute_fingerprint(source_provider=source_provider, tx=tx)
                group_fps.append(fp)
                group_items.append(
                    PreparedItem(
                        pos=i,
                        tx=tx,
                        external_id=eid,
                        fingerprint=fp,
                        suggested="",  # not used in persistence path
                    )
                )

            # Query duplicates once per group; when unanimous, auto-apply
            _dupes, unanimous = query_group_duplicates(
                session,
                source_provider=source_provider,
                source_account=source_account,
                group_eids=group_eids,
                group_fps=group_fps,
                exemplars=1,
            )
            if not unanimous:
                continue

            persist_group(
                session,
                source_provider=source_provider,
                source_account=source_account,
                group_items=group_items,
                final_cat=unanimous,
                category_source="rule",
            )
            session.commit()

            prefilled_positions.update(positions)
            prefilled_groups += 1

            # Log per-group application with normalized merchant key (ASCII, explicit quoting)
            key_short = key if len(key) <= 40 else (key[:37] + "...")
            _logger.info(
                'prefill:applied key="%s" size=%d category=%s',
                key_short,
                len(positions),
                unanimous,
            )

    # Final summary line to aid operators and tests
    _logger.info(
        "prefill:summary groups_applied=%d positions_assigned=%d",
        prefilled_groups,
        len(prefilled_positions),
    )
    return prefilled_positions, prefilled_groups


def _fan_out_group_decisions(
    original_seq: list[Mapping[str, Any]],
    *,
    exemplars: Sequence[int],
    by_key: Mapping[str, list[int]],
    singleton_indices: Sequence[int],
    group_details_by_exemplar: Mapping[int, LlmDecision],
) -> list[CategorizedTransaction]:
    """Apply group-level categorization details to all group members.

    Parameters
    ----------
    original_seq:
        Full input sequence (preserves output order).
    exemplars:
        Absolute indices of representative items for each group (sorted).
    by_key:
        Mapping from grouping key to absolute indices for members of that group.
    singleton_indices:
        Absolute indices of items that did not belong to any group.
    group_details_by_exemplar:
        Parsed LLM result details keyed by exemplar absolute index.

    Returns
    -------
    list[CategorizedTransaction]
        One entry per input item in ``original_seq``, preserving order.
    """

    # Precompute mapping from exemplar -> member indices (including itself)
    members_by_exemplar: dict[int, list[int]] = {ex: [] for ex in exemplars}
    for idxs in by_key.values():
        root = min(idxs)
        members_by_exemplar[root].extend(idxs)
    for i in singleton_indices:
        members_by_exemplar[i].append(i)

    # Prepare an output list and fill per group below. We avoid constructing
    # placeholders because `CategorizedTransaction` now requires `rationale`
    # and `score`.
    results: list[CategorizedTransaction | None] = [None] * len(original_seq)

    for exemplar_abs_idx, members in members_by_exemplar.items():
        details = group_details_by_exemplar.get(exemplar_abs_idx)
        if details is None:  # pragma: no cover - defensive: missing details for a group
            raise RuntimeError(
                f"Internal error: missing parsed details for exemplar index {exemplar_abs_idx}"
            )
        for m in members:
            results[m] = CategorizedTransaction(
                transaction=original_seq[m],
                category=details.category,
                rationale=details.rationale,
                score=details.score,
                revised_category=details.revised_category,
                revised_rationale=details.revised_rationale,
                revised_score=details.revised_score,
                citations=details.citations,
            )

    # Validate all positions were filled exactly once
    missing = [i for i, v in enumerate(results) if v is None]
    if missing:  # pragma: no cover - defensive
        raise RuntimeError(f"Internal error: missing categorized results at indices {missing}")
    # Cast away None for the type checker
    return [cast(CategorizedTransaction, r) for r in results]


def categorize_expenses(
    transactions: Transactions,
    taxonomy: Sequence[Mapping[str, Any]],
    *,
    page_size: int = _PAGE_SIZE_DEFAULT,
    source_provider: str = "amex",
) -> list[CategorizedTransaction]:
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
        Page size for batching requests (default 10). Must be a positive
        integer when ``transactions`` is not empty.

    Returns
    -------
    list[CategorizedTransaction]
        One result per input item, in the same order.

    Notes
    -----
    - If ``transactions`` is empty, this function returns ``[]`` without
      validating ``page_size`` (historical contract, preserved).
    """
    original_seq = _validate_and_materialize(transactions)
    n_total = len(original_seq)

    if n_total == 0:
        return []
    if not isinstance(page_size, int) or page_size <= 0:
        raise ValueError("page_size must be a positive integer")

    # Group before LLM
    exemplars, by_key, singleton_indices = _group_by_normalized_merchant(original_seq)

    n_groups = len(exemplars)

    # Static per-call components reused across pages
    system_instructions = prompting.build_system_instructions()

    # Build response schema from taxonomy
    response_format = prompting.build_response_format(taxonomy)
    text_cfg = ResponseTextConfigParam(
        format=response_format,
    )

    # Hold per-group parsed details keyed by exemplar absolute index
    group_details_by_exemplar: dict[int, LlmDecision] = {}

    # Build pages over exemplars
    pages: list[list[int]] = []
    for _, base, end in _paginate(n_groups, page_size):
        pages.append(exemplars[base:end])

    dataset_id = compute_dataset_id(
        ctv_items=original_seq,
        source_provider=source_provider,
        taxonomy=taxonomy,
    )

    def _map_page(page_index_and_indices: tuple[int, list[int]]) -> PageResult:
        page_index, indices = page_index_and_indices
        return _categorize_page(
            page_index,
            dataset_id=dataset_id,
            page_size=page_size,
            exemplar_abs_indices=indices,
            original_seq=original_seq,
            system_instructions=system_instructions,
            text_cfg=text_cfg,
            taxonomy=taxonomy,
            source_provider=source_provider,
        )

    page_inputs: list[tuple[int, list[int]]] = [(i, pg) for i, pg in enumerate(pages)]
    page_results: list[PageResult] = p_map(
        page_inputs, _map_page, concurrency=_CONCURRENCY, stop_on_error=True
    )
    for page in page_results:
        for exemplar_abs_idx, item in page.results:
            group_details_by_exemplar[exemplar_abs_idx] = item

    # Fan out group-level decisions to all members via helper
    results: list[CategorizedTransaction] = _fan_out_group_decisions(
        original_seq,
        exemplars=exemplars,
        by_key=by_key,
        singleton_indices=singleton_indices,
        group_details_by_exemplar=group_details_by_exemplar,
    )

    return results
