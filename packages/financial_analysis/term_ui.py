"""Tiny terminal UI helpers (prompt_toolkit-based).

This module contains small, focused helpers for interactive terminal prompts
that we want to keep decoupled from the core review/categorization logic so
they're easy to test in isolation.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter


def select_category(
    categories: Sequence[str] | Iterable[str],
    *,
    default: str,
    message: str = "Choose category (Enter to accept): ",
    session: PromptSession | None = None,
) -> str:
    """Prompt the user to choose a category using a completion dropdown.

    Parameters
    ----------
    categories:
        The canonical list of allowed category strings (order is preserved for
        how the completion menu is displayed).
    default:
        The initial, pre-filled value. Pressing Enter immediately confirms it.
    message:
        Prompt message shown to the user.
    session:
        Optional :class:`prompt_toolkit.PromptSession` to use (allows tests to
        inject custom input/output streams). When not provided, a fresh session
        is created per invocation.

    Returns
    -------
    str
        The selected category string.
    """

    words = list(categories)
    completer = WordCompleter(
        words,
        ignore_case=True,  # typing 'gro' matches 'Groceries'
        match_middle=True,  # 'eme' matches 'Emergency'
        sentence=False,
    )

    sess = session or PromptSession()
    # Render the built-in completion menu via the completer. The dropdown opens
    # on Tab or when navigating completions; Enter confirms the current buffer.
    result = sess.prompt(message, completer=completer, default=default)
    return result


__all__ = ["select_category"]
