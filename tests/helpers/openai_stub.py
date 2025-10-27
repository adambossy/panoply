"""Test helpers to stub the OpenAI Responses client used by categorize.py.

The stub parses the user-content payload to extract the embedded CTV JSON
array and returns a deterministic list of decision dicts. Tests provide a
``mapping`` callable to map each CTV item to a ``(category, score, rationale)``
tuple so the test surface stays small and focused on inputs/outputs.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

BEGIN = "BEGIN_TRANSACTIONS_JSON\n"
END = "\nEND_TRANSACTIONS_JSON"


def _extract_ctv_from_user_content(user_content: str) -> list[dict[str, Any]]:
    b = user_content.find(BEGIN)
    e = user_content.rfind(END)
    if b == -1 or e == -1 or e <= b:
        raise AssertionError("categorize: user content missing embedded CTV JSON block")
    ctv_json = user_content[b + len(BEGIN) : e]
    return json.loads(ctv_json)


class OpenAIStub:
    """Minimal stub matching ``openai.OpenAI`` shape for ``categorize.py``.

    Parameters
    ----------
    decide:
        A callable receiving a CTV item mapping and returning a
        ``(category, score, rationale)`` tuple. ``idx`` and optional ``id``
        fields from the input item are threaded through into the response.
    calls_out:
        A list that will be appended with each call's kwargs to allow tests to
        make lightweight assertions about paging or schema.
    """

    def __init__(
        self,
        decide: Callable[[dict[str, Any]], tuple[str, float, str]],
        calls_out: list[dict[str, Any]] | None = None,
    ) -> None:
        self._decide = decide
        self._calls = calls_out if calls_out is not None else []

        class _Responses:
            def __init__(self, outer: OpenAIStub) -> None:
                self._outer = outer

            def create(self, **kwargs):
                self._outer._calls.append(kwargs)
                items = _extract_ctv_from_user_content(kwargs["input"])
                results = []
                for item in items:
                    cat, score, rationale = self._outer._decide(item)
                    results.append(
                        {
                            "idx": item.get("idx", 0),
                            "id": item.get("id"),
                            "category": cat,
                            "rationale": rationale,
                            "score": float(score),
                        }
                    )

                class _Resp:
                    output_text: str

                resp = _Resp()
                resp.output_text = json.dumps({"results": results})
                return resp

        self.responses = _Responses(self)

    # Expose the captured calls list for assertions
    @property
    def calls(self) -> list[dict[str, Any]]:
        return self._calls
