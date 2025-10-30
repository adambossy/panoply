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
from promptorium import load_prompt

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
    """Return concise system instructions for two‑level taxonomy classification.

    Keep the model focused on: exactly one category from the provided taxonomy,
    prefer specific child over parent, never invent categories, and output JSON
    only per the schema.
    """

    return (
        "You are an agent that categorizes credit card transactions using the provided "
        "two-level taxonomy. Choose exactly one category per transaction (prefer the most "
        "specific child; otherwise the parent). Never invent categories. Output JSON only "
        "that conforms to the specified schema."
    )


def build_user_content(
    ctv_json: str,
    taxonomy: Sequence[Mapping[str, Any]],
) -> str:
    """Build user content centered around the refined instructions in Issue #88.

    - Embeds a concise, deterministic view of the two‑level taxonomy so the
      model can prefer children and fall back to parents.
    - Embeds the Transactions JSON delimited by BEGIN_/END_ markers with
      page‑relative ``idx`` for alignment.
    - Calls out the required response fields: ``category``, ``rationale``,
      ``score`` and the conditional ``revised_*`` plus ``citations`` when web
      search is used.
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

    template_text = load_prompt("fa-categorize")
    return template_text.replace("{{TAXONOMY_HIERARCHY}}", hierarchy_text).replace(
        "{{CTV_JSON}}", ctv_json
    )


def build_response_format(
    taxonomy: Sequence[Mapping[str, Any]],
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
                            "rationale": {"type": "string"},
                            "score": {"type": "number", "minimum": 0, "maximum": 1},
                            "revised_category": {
                                "type": ["string", "null"],
                                "enum": codes + [None],
                            },
                            "revised_rationale": {"type": ["string", "null"]},
                            "revised_score": {"type": ["number", "null"]},
                            "citations": {
                                "type": ["array", "null"],
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "idx",
                            "id",
                            "category",
                            "rationale",
                            "score",
                            "revised_category",
                            "revised_rationale",
                            "revised_score",
                            "citations",
                        ],
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
