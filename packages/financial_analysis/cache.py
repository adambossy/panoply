"""Dataset-level cache and shared caching utilities.

This module provides:

- ``compute_dataset_id``: stable identifier for a run over a specific input
  dataset and model/prompt settings.
- ``get_or_categorize_all``: dataset-wide categorization with a single call to
  :func:`financial_analysis.categorize.categorize_expenses`, backed by a
  single-file cache (``dataset.json``).
- Internal helpers shared with chunk I/O (cache root, settings hash, schema).

Cache layout (relative to the cache root, default: ``./.cache``):

- Dataset (preferred for review path):

  ``<cache_root>/<dataset_id>/dataset.json``

Atomicity: writes target ``.tmp`` first and then ``os.replace`` into place.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from . import prompting
from .models import CategorizedTransaction
from .persistence import compute_fingerprint

# Single schema version shared across cache files
SCHEMA_VERSION: int = 2


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


def _dataset_path(dataset_id: str) -> Path:
    root = _get_cache_root() / dataset_id
    root.mkdir(parents=True, exist_ok=True)
    return root / "dataset.json"


def read_dataset_from_cache(
    *,
    dataset_id: str,
    source_provider: str,
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
            fp_now = compute_fingerprint(source_provider=source_provider, tx=tx)
            if fp_now != fp:
                return None

            details = ent.get("llm", {}) or {}
            # Required fields
            rationale_v = details.get("rationale")
            score_v = details.get("score")
            if not isinstance(rationale_v, str):
                return None
            # NOTE: isinstance() requires a tuple of types; avoid PEP 604 here
            if not isinstance(score_v, int | float):
                return None
            # Optional revision fields
            revised_category_v = details.get("revised_category")
            if revised_category_v is not None and not isinstance(revised_category_v, str):
                return None
            revised_rationale_v = details.get("revised_rationale")
            if revised_rationale_v is not None and not isinstance(revised_rationale_v, str):
                return None
            revised_score_v = details.get("revised_score")
            if revised_score_v is not None and not isinstance(revised_score_v, int | float):
                return None
            # Normalize citations to an immutable tuple[str, ...]
            citations_raw = details.get("citations", []) or []
            if not isinstance(citations_raw, list) or not all(
                isinstance(c, str) for c in citations_raw
            ):
                return None
            citations_t = tuple(citations_raw)
            out.append(
                CategorizedTransaction(
                    transaction=tx,
                    category=cat,
                    rationale=rationale_v,
                    score=float(score_v),
                    revised_category=revised_category_v,
                    revised_rationale=revised_rationale_v,
                    revised_score=(float(revised_score_v) if revised_score_v is not None else None),
                    citations=citations_t,
                )
            )
        return out
    except Exception:
        return None


def write_dataset_to_cache(
    *,
    dataset_id: str,
    source_provider: str,
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
            "fp": compute_fingerprint(source_provider=source_provider, tx=item.transaction),
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
