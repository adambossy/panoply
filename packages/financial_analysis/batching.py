"""Chunked categorization with on-disk caching for fast review startup.

Public helpers used by the CLI review flow:

- ``compute_dataset_id``: stable identifier for a run over a specific input
  dataset and model/prompt settings. Used as the cache directory name.
- ``get_or_compute_chunk``: return categorized results for a chunk, reading
  from cache when available/valid or computing and writing atomically.
- ``spawn_background_chunk_worker``: sequentially pre-compute future chunks on
  a background thread while the operator reviews the current chunk.

Cache layout (relative to the cache root, default: ``./.transactions``):

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
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from typing import Any

from . import prompting
from .categorize import _MODEL  # private, but stable within this package
from .models import CategorizedTransaction
from .persistence import compute_fingerprint

# ----------------------------------------------------------------------------
# Cache roots and dataset identity
# ----------------------------------------------------------------------------


def _get_cache_root() -> Path:
    """Return the cache root directory.

    Default: ``./.transactions`` under the current working directory.
    Override: ``FA_CACHE_DIR`` environment variable (absolute or relative).
    """

    root = os.getenv("FA_CACHE_DIR")
    if root and root.strip():
        return Path(root).expanduser().resolve()
    # Use CWD by default, per #54 owner decision
    return (Path.cwd() / ".transactions").resolve()


def _settings_hash(
    allowed_categories: tuple[str, ...],
    *,
    taxonomy_hierarchy: Sequence[Mapping[str, object]] | None = None,
) -> str:
    """Hash model + categories + prompt schema/strings to invalidate cache on change.

    Includes a stable representation of the taxonomy hierarchy (when provided)
    so cache keys roll when parent/child relationships change, even if the flat
    allow‑list stays the same.
    """

    payload = {
        "model": _MODEL,
        "categories": list(allowed_categories),
        # Include the JSON Schema and instruction strings to capture prompt changes
        "response_format": prompting.build_response_format(allowed_categories),
        "system_instructions": prompting.build_system_instructions(),
        # Field order of CTV JSON also affects shape/semantics
        "ctv_fields": list(prompting.CTV_FIELD_ORDER),
    }
    if taxonomy_hierarchy is not None:
        # Reduce to a compact list of (code, parent_code, display_name) tuples for determinism
        th_min = [
            {
                "code": str(d.get("code")),
                "parent_code": (d.get("parent_code") or None),
                "display_name": str(d.get("display_name") or ""),
            }
            for d in taxonomy_hierarchy
        ]
        payload["taxonomy"] = sorted(th_min, key=lambda x: (x["parent_code"] or "", x["code"]))
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def compute_dataset_id(
    ctv_items: list[Mapping[str, Any]],
    *,
    source_provider: str,
    allowed_categories: tuple[str, ...],
    taxonomy_hierarchy: Sequence[Mapping[str, object]] | None = None,
) -> str:
    """Return a stable identifier for the input dataset + settings.

    Incorporates per-transaction fingerprints (order-sensitive) and the
    ``_settings_hash()`` so cache keys roll when the model/categories/prompts
    change.
    """

    fps: list[str] = [
        compute_fingerprint(source_provider=source_provider, tx=tx) for tx in ctv_items
    ]
    payload = {
        "fps": fps,
        "settings": _settings_hash(allowed_categories, taxonomy_hierarchy=taxonomy_hierarchy),
    }
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


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
            or raw.get("schema_version") != 1
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
            out.append(CategorizedTransaction(transaction=tx, category=ent["category"]))
        return out
    except Exception:
        return None


def _write_chunk_to_cache(meta: _ChunkMeta, items: list[CategorizedTransaction]) -> None:
    path = _chunk_path(meta.dataset_id, meta.chunk_idx)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "schema_version": 1,
        "dataset_id": meta.dataset_id,
        "chunk_index": meta.chunk_idx,
        "base": meta.base,
        "end": meta.end,
        "settings_hash": meta.settings_hash,
        "items": [
            {
                "fp": compute_fingerprint(source_provider=meta.provider, tx=item.transaction),
                "category": item.category,
            }
            for item in items
        ],
    }
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
    allowed_categories: tuple[str, ...],
    taxonomy_hierarchy: Sequence[Mapping[str, Any]] | None = None,
) -> list[CategorizedTransaction]:
    """Return categorized results for the ``chunk_idx`` slice.

    Order is preserved and aligned to ``ctv_items[base:end]``.
    """

    total = len(ctv_items)
    base, end = _chunk_bounds(chunk_idx, total=total, chunk_size=chunk_size)
    meta = _ChunkMeta(
        dataset_id=dataset_id,
        chunk_idx=chunk_idx,
        base=base,
        end=end,
        settings_hash=_settings_hash(
            allowed_categories, taxonomy_hierarchy=taxonomy_hierarchy
        ),
        provider=source_provider,
    )

    cached = _read_chunk_from_cache(meta, ctv_items=ctv_items)
    if cached is not None:
        return cached

    # Compute now and persist to cache atomically
    from .categorize import categorize_expenses

    slice_items = ctv_items[base:end]
    results = list(
        categorize_expenses(
            slice_items,
            allowed_categories=allowed_categories,
            taxonomy_hierarchy=taxonomy_hierarchy,
        )
    )
    # Add provider to transactions for stable fingerprinting in cache (non-destructive copy)
    to_cache: list[CategorizedTransaction] = []
    for r in results:
        tx = dict(r.transaction)
        tx.setdefault("provider", source_provider)
        to_cache.append(CategorizedTransaction(transaction=tx, category=r.category))

    _write_chunk_to_cache(meta, to_cache)
    # Return results with the original tx objects (without provider field addition)
    return results


def spawn_background_chunk_worker(
    *,
    dataset_id: str,
    start_chunk: int,
    total_chunks: int,
    ctv_items: list[Mapping[str, Any]],
    source_provider: str,
    chunk_size: int = 250,
    on_chunk_done: Callable[[int, float], None] | None = None,
    allowed_categories: tuple[str, ...] | None = None,
    taxonomy_hierarchy: Sequence[Mapping[str, Any]] | None = None,
) -> Thread:
    """Start a background worker that sequentially computes chunks start..N-1."""

    def _run() -> None:
        for k in range(start_chunk, total_chunks):
            t0 = time.perf_counter()
            try:
                get_or_compute_chunk(
                    dataset_id,
                    k,
                    ctv_items,
                    source_provider=source_provider,
                    chunk_size=chunk_size,
                    allowed_categories=allowed_categories if allowed_categories is not None else tuple(),
                    taxonomy_hierarchy=taxonomy_hierarchy,
                )
            except Exception:
                # Intentionally swallow to avoid crashing the main thread; the
                # foreground will surface errors when it reaches this chunk.
                pass
            else:
                if on_chunk_done is not None:
                    on_chunk_done(k, time.perf_counter() - t0)

    th = Thread(target=_run, name=f"fa-chunk-worker-{start_chunk}-{total_chunks}", daemon=True)
    th.start()
    return th


def total_chunks_for(total: int, *, chunk_size: int) -> int:
    return math.ceil(total / max(1, chunk_size))
