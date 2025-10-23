"""Prompt construction and CTV serialization for expense categorization.

This module builds:
- A deterministic JSON serialization of Canonical Transaction View (CTV)
  objects with a fixed field order.
- The system and user prompts for the categorization task.
- The strict ``response_format`` (JSON Schema) object for the OpenAI
  Responses API.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any
from openai.types.responses.response_format_text_json_schema_config_param import (
    ResponseFormatTextJSONSchemaConfigParam,
)

CTV_FIELD_ORDER: tuple[str, ...] = (
    "idx",
    "id",
    "description",
    "amount",
    "date",
    "merchant",
    "memo",
)


def serialize_ctv_to_json(ctv_items: Sequence[dict[str, Any]]) -> str:
    """Serialize CTV items to a JSON array with a fixed field order.

    Field order per object is exactly: ``idx, id, description, amount, date,
    merchant, memo``. Only standard JSON escaping is applied.
    """

    arr: list[dict[str, Any]] = []
    for item in ctv_items:
        out: dict[str, Any] = {}
        for key in CTV_FIELD_ORDER:
            out[key] = item.get(key)
        arr.append(out)
    # Compact separators to reduce size while keeping readability acceptable.
    return json.dumps(arr, ensure_ascii=False)


def build_system_instructions() -> str:
    """Return the system instructions for two‑level taxonomy classification.

    Behavior required by the product spec:
    - Categories come from a two‑level taxonomy (parents → children).
    - Always try to choose the most specific bottom‑level (child) category.
    - If no child clearly fits, choose the best matching top‑level (parent) category.
    - If neither level fits, fall back to "Other" or "Unknown" when allowed.
    - Output must be a single category string from the allowed set; no extra text.
    """

    return (
        "You are a precise expense categorization engine. Use the provided two-level "
        "taxonomy to choose exactly one category per transaction. Prefer the most "
        "specific bottom-level category; if none clearly applies, choose the best "
        "top-level category; if still no fit, use 'Other' or 'Unknown' when allowed. "
        "Never invent categories and do not include explanations."
    )


def build_user_content(
    ctv_json: str,
    taxonomy: Sequence[Mapping[str, Any]],
) -> str:
    """Build user content including an optional two‑level taxonomy section.

    Parameters
    ----------
    ctv_json:
        JSON array of page CTV items (with page‑relative ``idx`` fields).
    taxonomy:
        Sequence of mappings having at least ``code`` and
        ``parent_code`` keys. When provided, a concise hierarchy section is
        included so the model can prefer children and fall back to parents
        when needed.
    """
    hierarchy_text = ""

    # Group items by parent_code; None denotes top‑level. Sort deterministically.
    parents: list[Mapping[str, Any]] = sorted(
        [r for r in taxonomy if r.get("parent_code") in (None, "")],
        key=lambda r: (
            str(r.get("display_name") or r.get("code") or ""),
            str(r.get("code") or ""),
        ),
    )
    children_by_parent: dict[str, list[Mapping[str, Any]]] = {}
    for r in taxonomy:
        pc = r.get("parent_code")
        if pc:
            key = str(pc).strip()
            children_by_parent.setdefault(key, []).append(r)
    for k, v in list(children_by_parent.items()):
        children_by_parent[k] = sorted(
            v,
            key=lambda c: (
                str(c.get("display_name") or c.get("code") or ""),
                str(c.get("code") or ""),
            ),
        )

    lines: list[str] = [
        "\nTaxonomy (two levels):",
        "- Prefer a child when it clearly fits; otherwise use the parent.",
    ]
    for p in parents:
        p_code = str(p.get("code"))
        p_name = str(p.get("display_name") or p_code)
        # Show only display names to avoid redundant repetition.
        lines.append(f"  • {p_name}")
        kids = children_by_parent.get(p_code, [])
        if kids:
            # Compact one-per-line to keep prompts small and deterministic
            for c in kids:
                c_code = str(c.get("code"))
                c_name = str(c.get("display_name") or c_code)
                lines.append(f"    - {c_name}")
    hierarchy_text = "\n".join(lines) + "\n"

    header_target = "taxonomy below"

    return (
        f"Task: Categorize each transaction into exactly one category from the {header_target}.\n\n"
        f"{hierarchy_text}"
        "Rules:\n"
        "- Choose only one category for each transaction.\n"
        "- Prefer the most specific child; if no child fits, pick the best parent.\n"
        "- If neither level fits, use 'Other' or 'Unknown' only if present in the taxonomy.\n"
        "- Keep input order. Use the provided idx field to align responses.\n"
        "- Respond with JSON only, following the specified schema. No extra text.\n\n"
        "- Categorize every transaction in your output. DON'T DROP ANY TRANSACTIONS.\n"
        "Transactions JSON (UTF-8). Begin after the next line with "
        "BEGIN_TRANSACTIONS_JSON and end at END_TRANSACTIONS_JSON:\n"
        "BEGIN_TRANSACTIONS_JSON\n"
        f"{ctv_json}\n"
        "END_TRANSACTIONS_JSON"
    )


def build_response_format(
    taxonomy: Sequence[Mapping[str, Any]]
) -> ResponseFormatTextJSONSchemaConfigParam:
    """Return the strict JSON Schema response_format object from taxonomy.

    Schema shape:
    {
      "type": "json_schema",
      "name": "expense_categories",
      "schema": {
        "type": "object",
        "properties": {
          "results": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "idx": {"type": "integer"},
                "id": {"type": ["string", "null"]},
                "category": {"type": "string", "enum": [...]}
              },
              "required": ["idx", "id", "category"],
              "additionalProperties": false
            }
          }
        },
        "required": ["results"],
        "additionalProperties": false
      },
      "strict": true
    }
    """

    # Derive a deterministic flat list of codes from the taxonomy
    codes: list[str] = [
        c for c in dict.fromkeys(str(entry.get("code") or "").strip() for entry in taxonomy) if c
    ]

    if not codes:
        raise ValueError("taxonomy must contain at least one non-blank 'code'")

    result: ResponseFormatTextJSONSchemaConfigParam = {
        # Shape aligns with openai.types.responses.ResponseFormatTextJSONSchemaConfigParam
        "type": "json_schema",
        "name": "expense_categories",
        "schema": {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "idx": {"type": "integer"},
                            "id": {"type": ["string", "null"]},
                            "category": {"type": "string", "enum": codes},
                        },
                        "required": ["idx", "id", "category"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["results"],
            "additionalProperties": False,
        },
        "strict": True,
    }
    return result
