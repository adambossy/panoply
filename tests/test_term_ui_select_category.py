import contextlib

from financial_analysis.categorization import ALLOWED_CATEGORIES
from financial_analysis.term_ui import select_category_or_create

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


def test_select_category_or_create_accepts_default_with_enter():
    # Default predicted category is pre-filled; pressing Enter accepts it.
    default = "Groceries"
    with pipe_session() as (pipe, sess):
        pipe.send_text("\r")  # Enter
        result = select_category_or_create(list(ALLOWED_CATEGORIES), default=default, session=sess, allow_create=False)
        assert result == default


def test_select_category_or_create_change_via_completion():
    # Clear the default, type the target, then Enter.
    default = "Groceries"
    target = "Restaurants"
    with pipe_session() as (pipe, sess):
        # Ctrl-A (home), Ctrl-K (kill to end), type full target, Enter
        pipe.send_text("\x01\x0bRestaurants\r")
        result = select_category_or_create(list(ALLOWED_CATEGORIES), default=default, session=sess, allow_create=False)
        assert result == target


def test_down_arrow_or_tab_opens_dropdown_and_enter_accepts():
    # On an empty buffer, opening the dropdown and pressing Enter accepts the
    # highlighted selection (first item: "Groceries"). In headless CI we use
    # Tab to open deterministically.
    default = "Other"
    with pipe_session() as (pipe, sess):
        pipe.send_text("\x01\x0b")  # Ctrl-A, Ctrl-K to clear
        pipe.send_text("\t\r")  # Open via Tab, then Enter to accept first item
        result = select_category_or_create(list(ALLOWED_CATEGORIES), default=default, session=sess, allow_create=False)
        assert result == "Groceries"


def test_inline_suggestion_tab_autocompletes_prefix():
    # Typing a strict prefix shows greyed suggestion; Tab completes it.
    default = "Other"
    with pipe_session() as (pipe, sess):
        pipe.send_text("\x01\x0bGro\t\r")  # Clear, type 'Gro', Tab to complete, Enter
        result = select_category_or_create(list(ALLOWED_CATEGORIES), default=default, session=sess, allow_create=False)
        assert result == "Groceries"


def test_inline_suggestion_enter_commits_prefix_completion():
    # When a suggestion is visible, Enter should apply it and accept.
    default = "Other"
    with pipe_session() as (pipe, sess):
        pipe.send_text("\x01\x0bRes\r")  # Clear, type 'Res', Enter (should become Restaurants)
        result = select_category_or_create(list(ALLOWED_CATEGORIES), default=default, session=sess, allow_create=False)
        assert result == "Restaurants"


def test_exact_category_enter_returns_exact_value():
    default = "Other"
    with pipe_session() as (pipe, sess):
        pipe.send_text("\x01\x0bCoffee Shops\r")
        result = select_category_or_create(list(ALLOWED_CATEGORIES), default=default, session=sess, allow_create=False)
        assert result == "Coffee Shops"
