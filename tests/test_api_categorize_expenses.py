# ruff: noqa: E402, I001
import json
import time
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
import financial_analysis.categorize as categorize_mod  # noqa: E402
from financial_analysis.categorize import categorize_expenses as _categorize_expenses  # noqa: E402

# Flat test taxonomy allow‑list (parents and children). Keep small but representative.
TEST_ALLOWED_CATEGORIES: tuple[str, ...] = (
    "Groceries",
    "Restaurants",
    "Coffee Shops",
    "Flights",
    "Hotels",
    "Clothing",
    "Shopping",
    "Baby",
    "House",
    "Pet",
    "Emergency",
    "Medical",
    "Other",
)


# ---- Helpers -----------------------------------------------------------------


def _make_openai_stub(response_obj: Any, calls_out: list[dict[str, Any]]):
    """Return a minimal stub class to monkeypatch ``financial_analysis.categorize.OpenAI``.

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
    monkeypatch.setattr(categorize_mod, "OpenAI", OpenAIStub)
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


def _extract_ctv_from_user_content(user_content: str) -> list[dict[str, Any]]:
    """Helper to parse the embedded CTV JSON array from the user content string."""
    begin = "BEGIN_TRANSACTIONS_JSON\n"
    end = "\nEND_TRANSACTIONS_JSON"
    b = user_content.find(begin)
    e = user_content.rfind(end)
    assert b != -1 and e != -1 and e > b
    ctv_json = user_content[b + len(begin) : e]
    return json.loads(ctv_json)


class _PagedOpenAIStub:
    """A stubbed OpenAI client that returns page-sized results and tracks concurrency.

    - Builds ``results`` based on the number of CTV items in the input user content.
    - Records each call's kwargs into ``calls`` for later assertions.
    - Tracks ``inflight`` and ``max_inflight`` across threads to observe concurrency.
    - Optional ``sleep_per_call`` delays response to make concurrency measurable.
    """

    def __init__(self, calls: list[dict[str, Any]], sleep_per_call: float = 0.0):
        import threading

        self.calls = calls
        self.sleep_per_call = sleep_per_call
        self._lock = threading.Lock()
        self.inflight = 0
        self.max_inflight = 0

        class _Responses:
            def __init__(self, outer: "_PagedOpenAIStub") -> None:
                self._outer = outer

            def create(self, **kwargs):
                # Concurrency tracking
                with self._outer._lock:
                    self._outer.inflight += 1
                    if self._outer.inflight > self._outer.max_inflight:
                        self._outer.max_inflight = self._outer.inflight

                try:
                    self._outer.calls.append(kwargs)
                    user_content = kwargs["input"]
                    items = _extract_ctv_from_user_content(user_content)

                    # Simple synthetic categories (allowed)
                    results = [
                        {
                            "idx": item["idx"],
                            "id": item.get("id"),
                            "category": "Other",
                        }
                        for item in items
                    ]

                    if self._outer.sleep_per_call > 0:
                        time.sleep(self._outer.sleep_per_call)

                    class _Resp:
                        output_text: str

                    resp = _Resp()
                    resp.output_text = _mk_response_json(results)
                    return resp
                finally:
                    with self._outer._lock:
                        self._outer.inflight -= 1

        self.responses = _Responses(self)


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

    out = list(
        _categorize_expenses(
            transactions, allowed_categories=TEST_ALLOWED_CATEGORIES, taxonomy_hierarchy=None
        )
    )

    # Basic assertions
    assert len(out) == len(transactions)
    assert out[0].transaction is transactions[0]
    assert out[1].transaction is transactions[1]
    assert out[0].category in TEST_ALLOWED_CATEGORIES
    assert out[1].category in TEST_ALLOWED_CATEGORIES
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

    out = list(
        _categorize_expenses(
            transactions, allowed_categories=TEST_ALLOWED_CATEGORIES, taxonomy_hierarchy=None
        )
    )
    assert len(out) == 2
    assert out[0].transaction is transactions[0]
    assert out[1].transaction is transactions[1]
    assert out[0].category in TEST_ALLOWED_CATEGORIES
    assert out[1].category in TEST_ALLOWED_CATEGORIES


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

    out = list(
        _categorize_expenses(
            transactions, allowed_categories=TEST_ALLOWED_CATEGORIES, taxonomy_hierarchy=None
        )
    )
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

    out = list(
        _categorize_expenses(
            transactions, allowed_categories=TEST_ALLOWED_CATEGORIES, taxonomy_hierarchy=None
        )
    )
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
        list(
            _categorize_expenses(
                transactions,
                allowed_categories=TEST_ALLOWED_CATEGORIES,
                taxonomy_hierarchy=None,
            )
        )
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
        list(
            _categorize_expenses(
                transactions,
                allowed_categories=TEST_ALLOWED_CATEGORIES,
                taxonomy_hierarchy=None,
            )
        )
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
        list(
            _categorize_expenses(
                transactions,
                allowed_categories=TEST_ALLOWED_CATEGORIES,
                taxonomy_hierarchy=None,
            )
        )
    assert "Unexpected Responses API shape" in str(ei.value)


def test_malformed_json_raises(monkeypatch: pytest.MonkeyPatch):
    transactions = _mk_transactions()

    class Resp:
        output_text: str

    resp = Resp()
    resp.output_text = "this is not json"

    _run_with_stubbed_openai(monkeypatch, resp)

    with pytest.raises(ValueError) as ei:
        list(
            _categorize_expenses(
                transactions,
                allowed_categories=TEST_ALLOWED_CATEGORIES,
                taxonomy_hierarchy=None,
            )
        )
    assert "not valid JSON" in str(ei.value)


def test_empty_input_returns_empty_iterable(monkeypatch: pytest.MonkeyPatch):
    transactions: list[dict[str, Any]] = []

    class Resp:
        output_text: str

    resp = Resp()
    # For empty input, parser expects results=[]
    resp.output_text = _mk_response_json([])

    _run_with_stubbed_openai(monkeypatch, resp)

    out = list(
        _categorize_expenses(
            transactions, allowed_categories=TEST_ALLOWED_CATEGORIES, taxonomy_hierarchy=None
        )
    )
    assert out == []


@pytest.mark.parametrize(
    "n, expected_calls",
    [
        (0, 0),
        (50, 1),
        (100, 1),
        (101, 2),
        (200, 2),
        (250, 3),
        (1234, 13),  # 12x100 + 1x34
    ],
)
def test_pagination_call_counts_and_sizes(
    monkeypatch: pytest.MonkeyPatch, n: int, expected_calls: int
):
    # Build N synthetic transactions in input order; IDs are stable but unused by alignment.
    txs = [
        {
            "id": f"tx{i}",
            "description": f"desc {i}",
            "amount": -1.0,
            "date": "2025-09-01",
            "merchant": "M",
            "memo": None,
        }
        for i in range(n)
    ]

    calls: list[dict[str, Any]] = []
    stub = _PagedOpenAIStub(calls)
    monkeypatch.setattr(categorize_mod, "OpenAI", lambda: stub)

    out = list(
        _categorize_expenses(
            txs, allowed_categories=TEST_ALLOWED_CATEGORIES, taxonomy_hierarchy=None
        )
    )

    # Count calls and verify page sizes never exceed the default (100)
    assert len(calls) == expected_calls
    for call in calls:
        items = _extract_ctv_from_user_content(call["input"])
        assert len(items) <= 100

    # Output shape and order preserved
    assert len(out) == n
    for i, row in enumerate(out):
        if n == 0:
            break
        assert row.transaction is txs[i]


def test_kw_only_page_size_override_changes_call_count(monkeypatch: pytest.MonkeyPatch):
    n = 120
    txs = [
        {
            "id": f"tx{i}",
            "description": f"desc {i}",
            "amount": -1.0,
            "date": "2025-09-01",
            "merchant": "M",
            "memo": None,
        }
        for i in range(n)
    ]

    calls: list[dict[str, Any]] = []
    stub = _PagedOpenAIStub(calls)
    monkeypatch.setattr(categorize_mod, "OpenAI", lambda: stub)

    # Override to a smaller page size; expect 3 calls (50, 50, 20)
    out = list(
        _categorize_expenses(
            txs, page_size=50, allowed_categories=TEST_ALLOWED_CATEGORIES, taxonomy_hierarchy=None
        )
    )
    assert len(out) == n
    assert len(calls) == 3
    sizes = [len(_extract_ctv_from_user_content(c["input"])) for c in calls]
    assert sizes[:2] == [50, 50]
    assert sizes[2] == 20


def test_bounded_concurrency_does_not_exceed_4(monkeypatch: pytest.MonkeyPatch):
    # Choose N to produce many pages and add a small sleep per call to expose concurrency.
    n = 1000  # 10 pages at default page size (100)
    txs = [
        {
            "id": f"tx{i}",
            "description": f"desc {i}",
            "amount": -1.0,
            "date": "2025-09-01",
            "merchant": "M",
            "memo": None,
        }
        for i in range(n)
    ]

    calls: list[dict[str, Any]] = []
    stub = _PagedOpenAIStub(calls, sleep_per_call=0.05)
    monkeypatch.setattr(categorize_mod, "OpenAI", lambda: stub)

    out = list(
        _categorize_expenses(
            txs, allowed_categories=TEST_ALLOWED_CATEGORIES, taxonomy_hierarchy=None
        )
    )
    assert len(out) == n
    # 10 pages → 10 calls
    assert len(calls) == 10
    # Observed in-flight maximum must not exceed the cap of 4
    assert stub.max_inflight <= 4
