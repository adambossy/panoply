"""Thin client for the OpenAI Responses API.

Non-streaming POST to ``https://api.openai.com/v1/responses`` using the
environment variable ``OPENAI_API_KEY`` for authentication. Returns the parsed
JSON response body as a Python mapping suitable for downstream validation.

This client intentionally omits performance handling, quotas, retries, logging,
and observability concerns.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

OPENAI_API_URL = "https://api.openai.com/v1/responses"


def post_responses(
    *, instructions: str, user_input: str, response_format: Mapping[str, Any]
) -> dict[str, Any]:
    """Execute a non-streaming Responses API call and return parsed JSON.

    Parameters
    ----------
    instructions:
        System prompt string.
    user_input:
        User content string containing categories, rules, and delimited JSON.
    response_format:
        Strict JSON schema object as defined in :mod:`financial_analysis.prompting`.
    """

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is required for OpenAI access")

    payload = {
        "model": "gpt-5",
        "instructions": instructions,
        "input": user_input,
        "response_format": response_format,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(OPENAI_API_URL, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        # Read error body if available to surface a helpful message
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - defensive fallback, keep simple per spec
            err_body = ""
        raise RuntimeError(f"OpenAI API error: {e.code} {e.reason}: {err_body}") from e

    # Parse JSON and return
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:  # pragma: no cover - kept minimal per spec
        raise ValueError("Failed to parse JSON from OpenAI Responses API") from e
