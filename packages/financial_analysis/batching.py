"""Chunked caching helpers for categorization.

Public helper:

- ``get_or_compute_chunk``: legacy per‑chunk cache used by older flows; kept
  for compatibility with tools that still depend on it.

Cache layout (relative to the cache root, default: ``./.cache``):

- Legacy chunk files (still supported for other callers):

  ``<cache_root>/<dataset_id>/chunks/batch-00000.json``

Each chunk file contains::

    {
      "schema_version": <schema_version>,
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

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cache import SCHEMA_VERSION, _get_cache_root, _settings_hash
from .models import CategorizedTransaction
from .persistence import compute_fingerprint

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
