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
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from . import prompting
from .persistence import compute_fingerprint

# Single schema version shared across cache files
SCHEMA_VERSION: int = 2


_DATASET_ID_RE = re.compile(r"^[a-f0-9]{64}$")


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
    ctv_items: list[Mapping[str, Any]],
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
# Dataset I/O (single-file cache)
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
) -> list[tuple[int, dict[str, Any]]] | None:
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
        raw = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(raw, dict)
            or raw.get("schema_version") != SCHEMA_VERSION
            or raw.get("dataset_id") != dataset_id
            or raw.get("page_size") != page_size
            or raw.get("page_index") != page_index
            or raw.get("settings_hash") != _settings_hash(taxonomy)
        ):
            return None

        ex = raw.get("exemplars")
        if not isinstance(ex, list) or len(ex) != len(exemplar_abs_indices):
            return None

        # Validate each exemplar's absolute index and fingerprint
        for j, ent in enumerate(ex):
            if not isinstance(ent, dict):
                return None
            abs_idx_v = ent.get("abs_index")
            fp_v = ent.get("fp")
            if not isinstance(abs_idx_v, int) or not isinstance(fp_v, str):
                return None
            if abs_idx_v != exemplar_abs_indices[j]:
                return None
            tx = original_seq[abs_idx_v]
            if compute_fingerprint(source_provider=source_provider, tx=tx) != fp_v:
                return None

        items = raw.get("items")
        if not isinstance(items, list) or len(items) != len(exemplar_abs_indices):
            return None

        exemplar_set = set(exemplar_abs_indices)
        idx_to_details: dict[int, dict[str, Any]] = {}
        for ent in items:
            if not isinstance(ent, dict):
                return None
            abs_index = ent.get("abs_index")
            det = ent.get("details")
            if not isinstance(abs_index, int) or not isinstance(det, dict):
                return None
            # Ensure 1:1 alignment and uniqueness
            if abs_index not in exemplar_set or abs_index in idx_to_details:
                return None
            # Light sanity of required detail fields (types only)
            cat = det.get("category")
            rationale_v = det.get("rationale")
            score_v = det.get("score")
            if not isinstance(cat, str) or not isinstance(rationale_v, str):
                return None
            if not isinstance(score_v, (int, float)):  # noqa: UP038 - isinstance() requires tuple
                return None
            idx_to_details[abs_index] = det

        # Emit in exemplar order for deterministic downstream behavior
        out = [(abs_i, idx_to_details[abs_i]) for abs_i in exemplar_abs_indices]
        return out
    except Exception:
        return None


def write_page_to_cache(
    *,
    dataset_id: str,
    page_size: int,
    page_index: int,
    source_provider: str,
    taxonomy: Sequence[Mapping[str, object]],
    original_seq: list[Mapping[str, Any]],
    exemplar_abs_indices: list[int],
    items: list[tuple[int, dict[str, Any]]],
) -> None:
    path = _page_path(dataset_id, page_size=page_size, page_index=page_index)
    tmp = path.with_suffix(path.suffix + ".tmp")

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "page_size": page_size,
        "page_index": page_index,
        "settings_hash": _settings_hash(taxonomy),
        # Exemplars section supports alignment validation on read
        "exemplars": [
            {
                "abs_index": abs_i,
                "fp": compute_fingerprint(source_provider=source_provider, tx=original_seq[abs_i]),
            }
            for abs_i in exemplar_abs_indices
        ],
        # Items: one per exemplar, holding parsed details
        "items": [
            {
                "abs_index": abs_i,
                "details": det,
            }
            for (abs_i, det) in items
        ],
    }

    # Write atomically, cleaning up the temp file on failure
    import contextlib

    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise


# Back-compat note: dataset-level helpers were used in an earlier iteration of
# this PR. We keep the identifier helper and migrate caching to page files. The
# previous dataset-wide read/write functions have been removed from the public
# API to avoid encouraging whole-dataset caching.

