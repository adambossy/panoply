"""Chunked and dataset-level caching helpers for categorization.

Public helpers used by the CLI review flow:

- ``compute_dataset_id``: stable identifier for a run over a specific input
  dataset and model/prompt settings. Used as the cache directory name.
- ``get_or_compute_all``: return categorized results for the full dataset in a
  single call to :func:`financial_analysis.categorize.categorize_expenses`,
  reading/writing a single dataset-level cache file. This preserves on‑disk
  cache semantics without introducing a second batching layer.
- ``get_or_compute_chunk``: legacy per‑chunk cache used by older flows; kept
  for compatibility with tools that still depend on it.

Cache layout (relative to the cache root, default: ``./.cache``):

- Dataset (preferred for review path):

  ``<cache_root>/<dataset_id>/dataset.json``

- Legacy chunk files (still supported for other callers):

  ``<cache_root>/<dataset_id>/chunks/batch-00000.json``

Each chunk file contains::

    {
      "schema_version": 1,
      "dataset_id": "...",
      "chunk_index": 0,
      "base": 0,
      "end": 250,
      "settings_hash": "...",  # model/categories/prompt schema hash
      "items": [ {"fp": "sha256", "category": "Restaurants"}, ... ]
    }

Atomicity: we write to ``.tmp`` and then ``os.replace`` into place.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import prompting
from .categorize import _MODEL  # private, but stable within this package
from .models import CategorizedTransaction
from .persistence import compute_fingerprint

SCHEMA_VERSION: int = 2

# ----------------------------------------------------------------------------
# Cache roots and dataset identity
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


def _dataset_path(dataset_id: str) -> Path:
    root = _get_cache_root() / dataset_id
    root.mkdir(parents=True, exist_ok=True)
    return root / "dataset.json"


def _read_dataset_from_cache(
    *,
    dataset_id: str,
    provider: str,
    taxonomy: Sequence[Mapping[str, object]],
    ctv_items: list[Mapping[str, Any]],
) -> list[CategorizedTransaction] | None:
    """Return cached dataset results when present and valid; otherwise ``None``.

    Validates schema version, settings hash, item count, and per‑item
    fingerprints to ensure the cache matches the current inputs.
    """

    path = _dataset_path(dataset_id)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(raw, dict)
            or raw.get("schema_version") != SCHEMA_VERSION
            or raw.get("dataset_id") != dataset_id
            or raw.get("count") != len(ctv_items)
            or raw.get("settings_hash") != _settings_hash(taxonomy)
        ):
            return None
        items = raw.get("items")
        if not isinstance(items, list) or len(items) != len(ctv_items):
            return None

        out: list[CategorizedTransaction] = []
        for i, ent in enumerate(items):
            if not isinstance(ent, dict):
                return None
            fp = ent.get("fp")
            cat = ent.get("category")
            if not isinstance(fp, str) or not isinstance(cat, str):
                return None
            # Verify fingerprint alignment
            tx = ctv_items[i]
            fp_now = compute_fingerprint(source_provider=provider, tx=tx)
            if fp_now != fp:
                return None

            details = ent.get("llm", {}) or {}
            # Normalize citations to an immutable tuple for our model
            citations = tuple(details.get("citations", []) or [])
            out.append(
                CategorizedTransaction(
                    transaction=tx,
                    category=cat,
                    rationale=details.get("rationale"),
                    score=details.get("score"),
                    revised_category=details.get("revised_category"),
                    revised_rationale=details.get("revised_rationale"),
                    revised_score=details.get("revised_score"),
                    citations=citations,
                )
            )
        return out
    except Exception:
        return None


def _write_dataset_to_cache(
    *,
    dataset_id: str,
    provider: str,
    taxonomy: Sequence[Mapping[str, object]],
    items: list[CategorizedTransaction],
) -> None:
    path = _dataset_path(dataset_id)
    tmp = path.with_suffix(path.suffix + ".tmp")

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "count": len(items),
        "settings_hash": _settings_hash(taxonomy),
        "items": [],
    }

    items_out: list[dict[str, Any]] = []
    for item in items:
        entry: dict[str, Any] = {
            "fp": compute_fingerprint(source_provider=provider, tx=item.transaction),
            "category": item.category,
            "llm": {
                "rationale": item.rationale,
                "score": item.score,
                "revised_category": item.revised_category,
                "revised_rationale": item.revised_rationale,
                "revised_score": item.revised_score,
                "citations": list(item.citations or []),
            },
        }
        items_out.append(entry)
    payload["items"] = items_out

    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def get_or_compute_all(
    dataset_id: str,
    ctv_items: list[Mapping[str, Any]],
    *,
    source_provider: str,
    taxonomy: Sequence[Mapping[str, Any]],
) -> list[CategorizedTransaction]:
    """Return categorized results for the entire dataset with a single API call.

    This thin wrapper preserves the CLI's on‑disk cache semantics without adding
    a second batching layer: it defers all request batching to
    :func:`financial_analysis.categorize.categorize_expenses` (which groups into
    pages and uses ``p_map`` for bounded parallelism).
    """

    cached = _read_dataset_from_cache(
        dataset_id=dataset_id,
        provider=source_provider,
        taxonomy=taxonomy,
        ctv_items=ctv_items,
    )
    if cached is not None:
        return cached

    from .categorize import categorize_expenses

    results = list(categorize_expenses(ctv_items, taxonomy=taxonomy))
    _write_dataset_to_cache(
        dataset_id=dataset_id,
        provider=source_provider,
        taxonomy=taxonomy,
        items=results,
    )
    return results


# ----------------------------------------------------------------------------
# Chunk I/O
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class _ChunkMeta:
    dataset_id: str
    chunk_idx: int
    base: int
    end: int
    settings_hash: str
    provider: str


def _chunk_bounds(chunk_idx: int, *, total: int, chunk_size: int) -> tuple[int, int]:
    base = chunk_idx * chunk_size
    end = min(base + chunk_size, total)
    return base, end


def _chunk_path(dataset_id: str, chunk_idx: int) -> Path:
    root = _get_cache_root() / dataset_id / "chunks"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"batch-{chunk_idx:05d}.json"


def _read_chunk_from_cache(
    meta: _ChunkMeta, *, ctv_items: list[Mapping[str, Any]]
) -> list[CategorizedTransaction] | None:
    path = _chunk_path(meta.dataset_id, meta.chunk_idx)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(raw, dict)
            or raw.get("schema_version") != SCHEMA_VERSION
            or raw.get("dataset_id") != meta.dataset_id
            or raw.get("chunk_index") != meta.chunk_idx
            or raw.get("base") != meta.base
            or raw.get("end") != meta.end
            or raw.get("settings_hash") != meta.settings_hash
        ):
            return None
        items = raw.get("items")
        if not isinstance(items, list) or (meta.end - meta.base) != len(items):
            return None

        # Validate fingerprints align exactly with the current slice
        for i, ent in enumerate(items):
            if not isinstance(ent, dict):
                return None
            fp = ent.get("fp")
            cat = ent.get("category")
            # Minimal validation: fp and category required; llm details optional
            if not isinstance(fp, str) or not isinstance(cat, str):
                return None
            tx = ctv_items[meta.base + i]
            fp_now = compute_fingerprint(source_provider=meta.provider, tx=tx)
            # Note: provider is constant across the CLI run; we pass the same here.
            # Any change in normalization will change fp_now and invalidate the cache.
            if fp_now != fp:
                return None

        # Construct results using the original transactions and cached categories
        out: list[CategorizedTransaction] = []
        for i, ent in enumerate(items):
            tx = ctv_items[meta.base + i]
            # Optional llm details (nested in cache); map to inlined fields
            details = ent.get("llm", {})
            details["citations"] = tuple(details.get("citations", []))
            out.append(CategorizedTransaction(transaction=tx, category=ent["category"], **details))
        return out
    except Exception:
        return None


def _write_chunk_to_cache(meta: _ChunkMeta, items: list[CategorizedTransaction]) -> None:
    path = _chunk_path(meta.dataset_id, meta.chunk_idx)
    tmp = path.with_suffix(path.suffix + ".tmp")
    items_out: list[dict[str, Any]] = []
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": meta.dataset_id,
        "chunk_index": meta.chunk_idx,
        "base": meta.base,
        "end": meta.end,
        "settings_hash": meta.settings_hash,
        "items": items_out,
    }
    for item in items:
        entry: dict[str, Any] = {
            "fp": compute_fingerprint(source_provider=meta.provider, tx=item.transaction),
            "category": item.category,
            "llm": {
                "rationale": item.rationale,
                "score": item.score,
                "revised_category": item.revised_category,
                "revised_rationale": item.revised_rationale,
                "revised_score": item.revised_score,
                "citations": list(item.citations or []),
            },
        }
        items_out.append(entry)
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


# ----------------------------------------------------------------------------
# Public chunk API
# ----------------------------------------------------------------------------


def get_or_compute_chunk(
    dataset_id: str,
    chunk_idx: int,
    ctv_items: list[Mapping[str, Any]],
    *,
    source_provider: str,
    chunk_size: int = 250,
    taxonomy: Sequence[Mapping[str, Any]],
) -> list[CategorizedTransaction]:
    """Return categorized results for the ``chunk_idx`` slice.

    Order is preserved and aligned to ``ctv_items[base:end]``.
    """

    total = len(ctv_items)
    base, end = _chunk_bounds(chunk_idx, total=total, chunk_size=chunk_size)
    # Use taxonomy to compute settings hash
    meta = _ChunkMeta(
        dataset_id=dataset_id,
        chunk_idx=chunk_idx,
        base=base,
        end=end,
        settings_hash=_settings_hash(taxonomy),
        provider=source_provider,
    )

    cached = _read_chunk_from_cache(meta, ctv_items=ctv_items)
    if cached is not None:
        return cached

    # Compute now and persist to cache atomically
    from .categorize import categorize_expenses

    slice_items = ctv_items[base:end]
    results = list(categorize_expenses(slice_items, taxonomy=taxonomy))
    # Add provider to transactions for stable fingerprinting in cache (non-destructive copy)
    to_cache: list[CategorizedTransaction] = []
    for r in results:
        tx = dict(r.transaction)
        tx.setdefault("provider", source_provider)
        # Preserve LLM details in cache by forwarding inlined fields.
        to_cache.append(
            CategorizedTransaction(
                transaction=tx,
                category=r.category,
                rationale=r.rationale,
                score=r.score,
                revised_category=r.revised_category,
                revised_rationale=r.revised_rationale,
                revised_score=r.revised_score,
                citations=r.citations,
            )
        )

    _write_chunk_to_cache(meta, to_cache)
    # Return results with the original tx objects (without provider field addition)
    return results


def total_chunks_for(total: int, *, chunk_size: int) -> int:
    return math.ceil(total / max(1, chunk_size))
