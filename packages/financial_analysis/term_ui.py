"""Tiny terminal UI helpers (prompt_toolkit-based).

This module contains small, focused helpers for interactive terminal prompts
that we want to keep decoupled from the core review/categorization logic so
they're easy to test in isolation.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style


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
        match_middle=True,  # 'eme' matches 'Emergency' in dropdown
        sentence=False,
    )

    # Inline, greyed-out suggestion that completes the current typed prefix to
    # the top matching category (case-insensitive). We only suggest on strict
    # prefixes (not middle matches) and never when the current text already
    # equals a full allowed value (case-insensitive).
    class _PrefixAutoSuggest(AutoSuggest):
        def __init__(self, vocab: Sequence[str]) -> None:
            self._vocab = list(vocab)

        def get_suggestion(self, buffer, document):
            text = document.text
            if not text:
                return None
            lower = text.lower()
            # If already an exact match of an allowed value, don't suggest.
            for w in self._vocab:
                if w.lower() == lower:
                    return None
            # Pick the first item that startswith the typed prefix.
            for w in self._vocab:
                wl = w.lower()
                if wl.startswith(lower):
                    remainder = w[len(text) :]
                    if remainder:
                        return Suggestion(remainder)
                    return None
            return None

    auto_suggest = _PrefixAutoSuggest(words)

    # Key bindings:
    # - Down arrow opens the completion dropdown (and moves selection).
    # - Tab inserts the inline suggestion when present; otherwise falls back to
    #   cycling completions.
    # - Enter accepts the highlighted completion when the menu is open;
    #   otherwise if an inline suggestion is present, apply it and accept;
    #   else accept the current buffer as-is.
    kb = KeyBindings()
    # Internal fallback state for environments where arrow keys/completion menu
    # aren't fully synthesized (e.g., headless tests with PipeInput). When we
    # open/cycle the menu via our bindings, track the intended selection index
    # so Enter can still commit a choice if prompt_toolkit's ``complete_state``
    # isn't populated.
    _menu_opened = False
    _menu_index = 0

    @kb.add("down", eager=True)
    def _(event) -> None:  # pragma: no cover - exercised via integration tests
        nonlocal _menu_opened, _menu_index
        b = event.app.current_buffer
        if b.complete_state is None:
            # Open the menu and select the first completion based on current text.
            b.start_completion(select_first=True)
            _menu_opened = True
            _menu_index = 0
        else:
            b.complete_next()
            _menu_opened = True
            _menu_index += 1

    def _best_prefix_match(text: str) -> str | None:
        if not text:
            return None
        lower = text.lower()
        for w in words:
            wl = w.lower()
            if wl == lower:
                return None
            if wl.startswith(lower):
                return w
        return None

    @kb.add("tab", eager=True)
    def _(event) -> None:  # pragma: no cover - exercised via tests
        nonlocal _menu_opened, _menu_index
        b = event.app.current_buffer
        # Prefer the visible inline suggestion when available; otherwise compute.
        s = getattr(b, "suggestion", None)
        suggestion_text = getattr(s, "text", None)
        if not suggestion_text:
            cand = _best_prefix_match(b.document.text)
            if cand:
                suggestion_text = cand[len(b.document.text) :]
        if suggestion_text:
            b.insert_text(suggestion_text)
        else:
            # No inline suggestion: behave like completion next/open.
            if b.complete_state is None:
                b.start_completion(select_first=True)
                _menu_opened = True
                _menu_index = 0
            else:
                b.complete_next()
                _menu_opened = True
                _menu_index += 1

    @kb.add("enter", eager=True)
    def _(event) -> None:  # pragma: no cover - exercised via tests
        nonlocal _menu_opened, _menu_index
        b = event.app.current_buffer
        # If a completion menu is open, accept the highlighted item.
        cs = b.complete_state
        if cs is not None and cs.current_completion is not None:
            b.apply_completion(cs.current_completion)
            event.app.current_buffer.validate_and_handle()
            return

        # If an inline suggestion is visible, or we can compute a best prefix
        # match, apply it and accept.
        s = getattr(b, "suggestion", None)
        suggestion_text = getattr(s, "text", None)
        if not suggestion_text:
            cand = _best_prefix_match(b.document.text)
            if cand:
                suggestion_text = cand[len(b.document.text) :]
        if suggestion_text:
            b.insert_text(suggestion_text)
            event.app.current_buffer.validate_and_handle()
            return

        # Otherwise, accept whatever is in the buffer. If we tried to open the
        # menu using bindings in a headless environment and the buffer is empty,
        # commit the currently tracked selection as a best-effort fallback.
        if _menu_opened and not b.document.text:
            # For empty input, treat completions as the full vocabulary order.
            idx = max(0, min(_menu_index, len(words) - 1))
            b.insert_text(words[idx])
            event.app.current_buffer.validate_and_handle()
            return
        event.app.current_buffer.validate_and_handle()

    # Style for the inline suggestion (ghost text) — subtle grey.
    style = Style.from_dict({"auto-suggestion": "fg:#888888"})

    # Ensure our key bindings are active. When a session is injected (tests),
    # create a new PromptSession that reuses the same input/output streams so
    # we can attach our bindings reliably across prompt_toolkit versions.
    if session is None:
        sess: PromptSession = PromptSession(key_bindings=kb)
    else:
        sess = PromptSession(
            input=getattr(session, "input", None),
            output=getattr(session, "output", None),
            key_bindings=kb,
        )
    result = sess.prompt(
        message,
        completer=completer,
        default=default,
        key_bindings=kb,
        auto_suggest=auto_suggest,
        style=style,
    )
    return result


__all__ = ["select_category"]
