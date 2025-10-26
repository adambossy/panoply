"""Caching utilities (page-level) and shared helpers.

This module provides:

- ``compute_dataset_id``: stable identifier for a run over a specific input
  dataset and model/prompt settings.
- Page cache helpers used by ``categorize._categorize_page`` to cache the
  OpenAI Responses call per page (page of exemplars), rather than caching the
  entire dataset.
- Internal helpers shared across cache I/O (cache root, settings hash, schema).

Cache layout (relative to the cache root, default: ``./.cache``):

- Page cache (preferred):

  ``<cache_root>/<dataset_id>/pages_ps<page_size>/<page_index>.json``

Atomicity: writes target ``.tmp`` first and then ``os.replace`` into place.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from . import prompting
from .logging_setup import get_logger
from .models import LlmDecision, PageCacheFile, PageExemplar, PageItem
from .persistence import compute_fingerprint

# Page-cache schema version (independent from any other cache schema versions).
# Bump only when the on-disk page JSON shape changes.
SCHEMA_VERSION: int = 3


_DATASET_ID_RE = re.compile(r"^[a-f0-9]{64}$")


_logger = get_logger("financial_analysis.cache")


def _validate_dataset_id(dataset_id: str) -> str:
    """Ensure the dataset identifier is a 64-char lowercase hex string.

    Prevents path traversal and misuse when callers supply an arbitrary string.
    """

    if not _DATASET_ID_RE.fullmatch(dataset_id):
        raise ValueError(
            "Invalid dataset_id: must be 64-char lowercase hex (sha256 hexdigest). "
            "Use compute_dataset_id()."
        )
    return dataset_id


# ----------------------------------------------------------------------------
# Cache root and settings identity
# ----------------------------------------------------------------------------


def _get_cache_root() -> Path:
    """Return the cache root directory.

    Default: ``./.cache`` under the current working directory.
    Override: ``FA_CACHE_DIR`` environment variable (absolute or relative).
    """

    root = os.getenv("FA_CACHE_DIR")
    if root and root.strip():
        return Path(root).expanduser().resolve()
    # Use CWD by default, per #54 owner decision
    return (Path.cwd() / ".cache").resolve()


def _settings_hash(
    taxonomy: Sequence[Mapping[str, object]],
) -> str:
    """Hash model + taxonomy + prompt schema/strings to invalidate cache on change.

    The taxonomy drives both the prompt (hierarchy text) and the JSON Schema
    enum. We include a compact, normalized representation so keys roll when
    codes, names, or relationships change.
    """

    from .categorize import _MODEL  # imported lazily to avoid circular import

    # Compact, normalized taxonomy representation (code, parent_code, display_name)
    th_min: list[dict[str, object]] = [
        {
            "code": str(d.get("code") or "").strip(),
            "parent_code": (str(d.get("parent_code") or "").strip() or None),
            "display_name": str(d.get("display_name") or "").strip(),
        }
        for d in taxonomy
    ]

    def _taxonomy_sort_key(x: Mapping[str, object]) -> tuple[str, str]:
        return (str(x.get("parent_code") or ""), str(x.get("code") or ""))

    th_sorted = sorted(th_min, key=_taxonomy_sort_key)

    # Use a wide value type to allow heterogeneous entries (lists, dicts, strings)
    payload: dict[str, object] = {
        "model": _MODEL,
        # Include the JSON Schema and instruction strings to capture prompt changes
        "response_format": prompting.build_response_format(th_sorted),
        "system_instructions": prompting.build_system_instructions(),
        # Field order of CTV JSON also affects shape/semantics
        "ctv_fields": list(prompting.CTV_FIELD_ORDER),
        "taxonomy": th_sorted,
    }
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def compute_dataset_id(
    ctv_items: Iterable[Mapping[str, Any]],
    *,
    source_provider: str,
    taxonomy: Sequence[Mapping[str, object]],
) -> str:
    """Return a stable identifier for the input dataset + settings.

    Incorporates per-transaction fingerprints (order-sensitive) and the
    ``_settings_hash()`` so cache keys roll when the model/taxonomy/prompts
    change.
    """

    fps: list[str] = [
        compute_fingerprint(source_provider=source_provider, tx=tx) for tx in ctv_items
    ]
    payload = {"fps": fps, "settings": _settings_hash(taxonomy)}
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------
# Page cache I/O
# ----------------------------------------------------------------------------


def _pages_dir(dataset_id: str, *, page_size: int) -> Path:
    """Return the directory that holds per-page cache files for a dataset.

    The directory name encodes the page size so caches remain valid when the
    paging configuration changes.
    """

    dataset_id = _validate_dataset_id(dataset_id)
    root = _get_cache_root() / dataset_id / f"pages_ps{page_size}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _page_path(dataset_id: str, *, page_size: int, page_index: int) -> Path:
    d = _pages_dir(dataset_id, page_size=page_size)
    # zero-pad for stable lexicographic ordering
    fname = f"{page_index:05d}.json"
    return d / fname


def read_page_from_cache(
    *,
    dataset_id: str,
    page_size: int,
    page_index: int,
    source_provider: str,
    taxonomy: Sequence[Mapping[str, object]],
    original_seq: list[Mapping[str, Any]],
    exemplar_abs_indices: list[int],
) -> list[tuple[int, LlmDecision]] | None:
    """Return cached page results when present and valid; otherwise ``None``.

    Validation checks:
    - schema version and dataset/page identity
    - settings hash (model/prompt/taxonomy)
    - exemplar count and per‑exemplar fingerprint alignment
    """

    path = _page_path(dataset_id, page_size=page_size, page_index=page_index)
    if not path.exists():
        return None

    try:
        text = path.read_text(encoding="utf-8")
        # Parse and validate structure with Pydantic; reject unknowns/coercions
        parsed = PageCacheFile.model_validate_json(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _logger.debug(
            (
                "page_cache:read_failed; falling back to compute "
                "dataset_id=%s page_index=%d page_size=%d path=%s"
            ),
            dataset_id,
            page_index,
            page_size,
            os.fspath(path),
            exc_info=True,
        )
        return None

    # Cheap identity checks; treat any mismatch as a cache miss.
    if (
        parsed.schema_version != SCHEMA_VERSION
        or parsed.dataset_id != dataset_id
        or parsed.page_size != page_size
        or parsed.page_index != page_index
        or parsed.settings_hash != _settings_hash(taxonomy)
    ):
        return None

    # Alignment checks
    if len(parsed.exemplars) != len(exemplar_abs_indices):
        return None

    # Exemplar indices must match caller-supplied indices exactly and in order
    for j, (exp_abs, supplied_abs) in enumerate(
        zip((e.abs_index for e in parsed.exemplars), exemplar_abs_indices, strict=True)
    ):
        if exp_abs != supplied_abs:
            return None
        # Fingerprint must match current original_seq payload
        tx = original_seq[exp_abs]
        if compute_fingerprint(source_provider=source_provider, tx=tx) != parsed.exemplars[j].fp:
            return None

    # Items must be a 1:1 mapping to the exemplar set with unique abs_index
    if len(parsed.items) != len(parsed.exemplars):
        return None
    exemplar_set = {e.abs_index for e in parsed.exemplars}
    idx_to_details: dict[int, LlmDecision] = {}
    for it in parsed.items:
        if it.abs_index not in exemplar_set or it.abs_index in idx_to_details:
            return None
        idx_to_details[it.abs_index] = it.details

    # Emit in exemplar order for deterministic downstream behavior
    return [(abs_i, idx_to_details[abs_i]) for abs_i in exemplar_abs_indices]


def write_page_to_cache(
    *,
    dataset_id: str,
    page_size: int,
    page_index: int,
    source_provider: str,
    taxonomy: Sequence[Mapping[str, object]],
    original_seq: list[Mapping[str, Any]],
    exemplar_abs_indices: list[int],
    items: list[tuple[int, LlmDecision]],
) -> None:
    path = _page_path(dataset_id, page_size=page_size, page_index=page_index)
    tmp = path.with_suffix(path.suffix + ".tmp")

    page = PageCacheFile(
        schema_version=SCHEMA_VERSION,
        dataset_id=dataset_id,
        page_size=page_size,
        page_index=page_index,
        settings_hash=_settings_hash(taxonomy),
        exemplars=[
            PageExemplar(
                abs_index=abs_i,
                fp=compute_fingerprint(source_provider=source_provider, tx=original_seq[abs_i]),
            )
            for abs_i in exemplar_abs_indices
        ],
        items=[PageItem(abs_index=abs_i, details=det) for (abs_i, det) in items],
    )

    # Write atomically, cleaning up the temp file on failure
    import contextlib

    try:
        tmp.write_text(
            json.dumps(page.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise
