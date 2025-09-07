# ruff: noqa: E402, I001
import json
import sys
from pathlib import Path
from typing import Any

import pytest


# Make sure the workspace `packages/` dir is on sys.path so `financial_analysis` is importable
_ROOT = Path(__file__).resolve().parents[1]
_PKG_DIR = _ROOT / "packages"
# Ensure `packages/` precedes the repo root on sys.path so local packages resolve first.
sys.path[:0] = [p for p in [str(_PKG_DIR), str(_ROOT)] if p not in sys.path]

# Public symbol under test
from financial_analysis import api as api_mod  # noqa: E402
from financial_analysis.api import categorize_expenses as _categorize_expenses  # noqa: E402
from financial_analysis.categorization import ALLOWED_CATEGORIES  # noqa: E402


# ---- Helpers -----------------------------------------------------------------


def _make_openai_stub(response_obj: Any, calls_out: list[dict[str, Any]]):
    """Return a minimal stub class to monkeypatch ``financial_analysis.api.OpenAI``.

    The stub captures calls to ``responses.create(...)`` and returns the
    provided ``response_obj``. ``calls_out`` will be appended with each
    invocation's kwargs for lightweight argument assertions.
    """

    class _Responses:
        def create(self, **kwargs):
            calls_out.append(kwargs)
            return response_obj

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None:  # noqa: D401
            self.responses = _Responses()

    return _Client


def _run_with_stubbed_openai(monkeypatch: pytest.MonkeyPatch, response_obj: Any):
    calls: list[dict[str, Any]] = []
    OpenAIStub = _make_openai_stub(response_obj, calls)
    monkeypatch.setattr(api_mod, "OpenAI", OpenAIStub)
    return calls


def _mk_transactions():
    return [
        {
            "id": "t1",
            "description": "Uber trip",
            "amount": -23.45,
            "date": "2025-08-10",
            "merchant": "Uber",
            "memo": None,
        },
        {
            "id": "t2",
            "description": "Whole Foods Market",
            "amount": -54.12,
            "date": "2025-08-11",
            "merchant": "Whole Foods",
            "memo": "",
        },
    ]


def _mk_response_json(results: list[dict[str, Any]]) -> str:
    return json.dumps({"results": results})


# ---- Test cases ---------------------------------------------------------------


def test_happy_path_output_text(monkeypatch: pytest.MonkeyPatch):
    transactions = _mk_transactions()

    # Shape A: preferred path via resp.output_text
    class Resp:
        output_text: str

    resp = Resp()
    resp.output_text = _mk_response_json(
        [
            {"idx": 0, "id": "t1", "category": "Shopping"},
            {"idx": 1, "id": "t2", "category": "Groceries"},
        ]
    )

    calls = _run_with_stubbed_openai(monkeypatch, resp)

    out = list(_categorize_expenses(transactions))

    # Basic assertions
    assert len(out) == len(transactions)
    assert out[0].transaction is transactions[0]
    assert out[1].transaction is transactions[1]
    assert out[0].category in ALLOWED_CATEGORIES
    assert out[1].category in ALLOWED_CATEGORIES
    # Ensure inputs were not mutated (no idx added)
    assert "idx" not in transactions[0] and "idx" not in transactions[1]

    # Minimal interaction assertions
    assert len(calls) == 1
    call = calls[0]
    assert call.get("model") == "gpt-5"
    text_cfg = call.get("text")
    assert isinstance(text_cfg, dict) and isinstance(text_cfg.get("format"), dict)


def test_happy_path_output_content_text_fallback(monkeypatch: pytest.MonkeyPatch):
    transactions = _mk_transactions()

    # Shape B: fallback path via resp.output[0].content[0].text
    class _Node:
        def __init__(self, text: str):
            self.text = text

    class _Msg:
        def __init__(self, text: str):
            self.content = [_Node(text)]

    class Resp:
        def __init__(self, text: str):
            self.output = [_Msg(text)]

    resp = Resp(
        _mk_response_json(
            [
                {"idx": 0, "id": "t1", "category": "Shopping"},
                {"idx": 1, "id": "t2", "category": "Groceries"},
            ]
        )
    )

    _run_with_stubbed_openai(monkeypatch, resp)

    out = list(_categorize_expenses(transactions))
    assert len(out) == 2
    assert out[0].transaction is transactions[0]
    assert out[1].transaction is transactions[1]
    assert out[0].category in ALLOWED_CATEGORIES
    assert out[1].category in ALLOWED_CATEGORIES


def test_invalid_category_falls_back_to_other(monkeypatch: pytest.MonkeyPatch):
    transactions = _mk_transactions()

    class Resp:
        output_text: str

    resp = Resp()
    resp.output_text = _mk_response_json(
        [
            {"idx": 0, "id": "t1", "category": "FooBar"},  # invalid
            {"idx": 1, "id": "t2", "category": "Groceries"},
        ]
    )

    _run_with_stubbed_openai(monkeypatch, resp)

    out = list(_categorize_expenses(transactions))
    assert out[0].category == "Other"
    assert out[1].category == "Groceries"


def test_alignment_by_idx_out_of_order(monkeypatch: pytest.MonkeyPatch):
    transactions = _mk_transactions()

    class Resp:
        output_text: str

    # Results come back out of order: idx 1 first, then idx 0
    resp = Resp()
    resp.output_text = _mk_response_json(
        [
            {"idx": 1, "id": "t2", "category": "Groceries"},
            {"idx": 0, "id": "t1", "category": "Shopping"},
        ]
    )

    _run_with_stubbed_openai(monkeypatch, resp)

    out = list(_categorize_expenses(transactions))
    # Output order must match input order regardless of response order
    assert out[0].transaction is transactions[0]
    assert out[1].transaction is transactions[1]
    assert out[0].category == "Shopping"
    assert out[1].category == "Groceries"


def test_input_validation_empty_description_raises(monkeypatch: pytest.MonkeyPatch):
    # One item has an empty/whitespace-only description
    transactions = [
        {
            "id": "t1",
            "description": "   ",  # invalid
            "amount": -1,
            "date": "2025-08-10",
            "merchant": "X",
            "memo": None,
        }
    ]

    # Still stub OpenAI to avoid accidental network if validation changed
    class Resp:
        output_text: str

    resp = Resp()
    resp.output_text = _mk_response_json([])
    _run_with_stubbed_openai(monkeypatch, resp)

    with pytest.raises(ValueError) as ei:
        list(_categorize_expenses(transactions))
    msg = str(ei.value)
    assert "description" in msg and ("empty" in msg or "missing" in msg)


def test_input_validation_non_mapping_item_raises(monkeypatch: pytest.MonkeyPatch):
    transactions: list[Any] = [
        {
            "id": "t1",
            "description": "ok",
            "amount": -1,
            "date": None,
            "merchant": None,
            "memo": None,
        },
        "not a mapping",
    ]

    class Resp:
        output_text: str

    resp = Resp()
    resp.output_text = _mk_response_json([])
    _run_with_stubbed_openai(monkeypatch, resp)

    with pytest.raises(TypeError) as ei:
        list(_categorize_expenses(transactions))
    assert "mapping (CTV)" in str(ei.value)


def test_unexpected_responses_shape_raises(monkeypatch: pytest.MonkeyPatch):
    transactions = _mk_transactions()

    # Malformed shape: neither output_text nor output[0].content[0].text present
    class Resp:
        output_text: str

    resp = Resp()
    # no attributes set

    _run_with_stubbed_openai(monkeypatch, resp)

    with pytest.raises(ValueError) as ei:
        list(_categorize_expenses(transactions))
    assert "Unexpected Responses API shape" in str(ei.value)


def test_malformed_json_raises(monkeypatch: pytest.MonkeyPatch):
    transactions = _mk_transactions()

    class Resp:
        output_text: str

    resp = Resp()
    resp.output_text = "this is not json"

    _run_with_stubbed_openai(monkeypatch, resp)

    with pytest.raises(ValueError) as ei:
        list(_categorize_expenses(transactions))
    assert "not valid JSON" in str(ei.value)


def test_empty_input_returns_empty_iterable(monkeypatch: pytest.MonkeyPatch):
    transactions: list[dict[str, Any]] = []

    class Resp:
        output_text: str

    resp = Resp()
    # For empty input, parser expects results=[]
    resp.output_text = _mk_response_json([])

    _run_with_stubbed_openai(monkeypatch, resp)

    out = list(_categorize_expenses(transactions))
    assert out == []
