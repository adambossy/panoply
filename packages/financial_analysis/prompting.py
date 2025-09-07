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
from collections.abc import Iterable, Sequence
from typing import Any

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
    """Return the exact system instructions required by the spec."""

    return (
        "You are a precise expense categorization engine. For each transaction, output "
        "exactly one category from the allowed set. If none apply, use 'Other'. Do not "
        "invent categories or include explanations."
    )


def build_user_content(ctv_json: str, *, allowed_categories: Iterable[str] | None = None) -> str:
    """Build the user content including categories, rules, and delimited JSON.

    The allowed categories list is rendered exactly as provided (one per line).
    If ``allowed_categories`` is omitted, callers should render them directly
    within the string prior to passing here; however, the public API path uses
    this function with an explicit list to avoid duplication.
    """

    cats = "\n".join(allowed_categories) + "\n" if allowed_categories is not None else ""
    return (
        "Task: Categorize each transaction into exactly one of the following categories:\n\n"
        f"{cats}"
        "\nRules:\n"
        "- Choose only one category for each transaction.\n"
        "- Default to 'Other' only when none of the listed categories apply.\n"
        "- Keep input order. Use the provided idx field to align responses.\n"
        "- Respond with JSON only, following the specified schema. No extra text.\n\n"
        "Transactions JSON (UTF-8). Begin after the next line with "
        "BEGIN_TRANSACTIONS_JSON and end at END_TRANSACTIONS_JSON:\n"
        "BEGIN_TRANSACTIONS_JSON\n"
        f"{ctv_json}\n"
        "END_TRANSACTIONS_JSON"
    )


def build_response_format(allowed_categories: Iterable[str]) -> dict[str, Any]:
    """Return the strict JSON Schema response_format object.

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

    return {
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
                            "category": {
                                "type": "string",
                                "enum": list(allowed_categories),
                            },
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
