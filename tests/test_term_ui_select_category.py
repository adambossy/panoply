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
