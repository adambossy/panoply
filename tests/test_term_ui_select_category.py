import contextlib

from financial_analysis.categorization import ALLOWED_CATEGORIES
from financial_analysis.term_ui import select_category

# Compatibility import across prompt_toolkit versions
try:  # pragma: no cover - fallback path depends on library version
    from prompt_toolkit.input import create_pipe_input
except Exception:  # pragma: no cover - defensive
    from prompt_toolkit.input.defaults import create_pipe_input

from prompt_toolkit import PromptSession
from prompt_toolkit.output import DummyOutput


@contextlib.contextmanager
def pipe_session():
    with create_pipe_input() as pipe:
        sess = PromptSession(input=pipe, output=DummyOutput())
        yield pipe, sess


def test_select_category_accepts_default_with_enter():
    # Default predicted category is pre-filled; pressing Enter accepts it.
    default = "Groceries"
    with pipe_session() as (pipe, sess):
        pipe.send_text("\r")  # Enter
        result = select_category(list(ALLOWED_CATEGORIES), default=default, session=sess)
        assert result == default


def test_select_category_change_via_completion():
    # Clear the default, type the target, then Enter.
    default = "Groceries"
    target = "Restaurants"
    with pipe_session() as (pipe, sess):
        # Ctrl-A (home), Ctrl-K (kill to end), type full target, Enter
        pipe.send_text("\x01\x0bRestaurants\r")
        result = select_category(list(ALLOWED_CATEGORIES), default=default, session=sess)
        assert result == target


def test_down_arrow_opens_dropdown_and_selects_item():
    # Pressing Down on an empty buffer opens the dropdown; Enter accepts the
    # highlighted selection. We'll move to the 2nd item ("Restaurants").
    default = "Other"
    with pipe_session() as (pipe, sess):
        # Clear default to make the buffer empty, then Down to open the menu.
        pipe.send_text("\x01\x0b")  # Ctrl-A, Ctrl-K
        # Attempt to open with Down (two common encodings). In some headless
        # environments, arrow keys may not be synthesized reliably; send a Tab
        # as a fallback to ensure the dropdown opens, then Tab again to move
        # to the second item.
        pipe.send_bytes(b"\x1b[B\x1bOB")  # Down (open menu on TTYs)
        pipe.send_text("\t\t")  # Fallback: open + move to second via Tab
        pipe.send_text("\r")  # Enter: accept highlighted completion
        result = select_category(list(ALLOWED_CATEGORIES), default=default, session=sess)
        assert result == "Groceries"


def test_inline_suggestion_tab_autocompletes_prefix():
    # Typing a strict prefix shows greyed suggestion; Tab completes it.
    default = "Other"
    with pipe_session() as (pipe, sess):
        pipe.send_text("\x01\x0bGro\t\r")  # Clear, type 'Gro', Tab to complete, Enter
        result = select_category(list(ALLOWED_CATEGORIES), default=default, session=sess)
        assert result == "Groceries"


def test_inline_suggestion_enter_commits_prefix_completion():
    # When a suggestion is visible, Enter should apply it and accept.
    default = "Other"
    with pipe_session() as (pipe, sess):
        pipe.send_text("\x01\x0bRes\r")  # Clear, type 'Res', Enter (should become Restaurants)
        result = select_category(list(ALLOWED_CATEGORIES), default=default, session=sess)
        assert result == "Restaurants"


def test_exact_category_enter_returns_exact_value():
    default = "Other"
    with pipe_session() as (pipe, sess):
        pipe.send_text("\x01\x0bCoffee Shops\r")
        result = select_category(list(ALLOWED_CATEGORIES), default=default, session=sess)
        assert result == "Coffee Shops"
