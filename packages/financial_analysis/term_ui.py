"""Tiny terminal UI helpers (prompt_toolkit-based).

This module contains small, focused helpers for interactive terminal prompts
that we want to keep decoupled from the core review/categorization logic so
they're easy to test in isolation.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style
from prompt_toolkit.validation import ValidationError, Validator

from .categories import validate_name as _validate_name

# ----------------------------------------------------------------------------
# Creation-aware selector and mini-prompt
# ----------------------------------------------------------------------------

CREATE_SENTINEL = "+ Create new category..."


class CreateCategoryRequest:
    """Return type for creation flow: carries the typed candidate name.

    The review flow will open a mini-prompt to confirm/adjust and then persist.
    """

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:  # pragma: no cover - trivial repr
        return f"CreateCategoryRequest(name={self.name!r})"


def select_category_or_create(
    categories: Sequence[str] | Iterable[str],
    *,
    default: str,
    message: str = "Choose category (Enter to accept): ",
    session: PromptSession | None = None,
    allow_create: bool = True,
) -> str | CreateCategoryRequest:
    """Prompt the user to choose a category; optionally offer creation.

    Returns either a selected category string or a ``CreateCategoryRequest``
    when the user intends to create a new one (typed a non-existent value or
    picked the explicit "+ Create new category…" option).
    """

    words = list(categories)
    if allow_create:
        words = list(words) + [CREATE_SENTINEL]
    lower_set = {w.lower(): w for w in words if w != CREATE_SENTINEL}

    completer = WordCompleter(
        words,
        ignore_case=True,
        match_middle=True,
        sentence=False,
    )

    class _SuggestOrCreate(AutoSuggest):
        def __init__(self, vocab: Sequence[str], allow_create: bool) -> None:
            self._vocab = [w for w in vocab if w != CREATE_SENTINEL]
            self._allow_create = allow_create

        def get_suggestion(self, buffer, document):
            text = document.text
            if not text:
                return None
            lower = text.lower()
            # Exact match? No suggestion.
            for w in self._vocab:
                if w.lower() == lower:
                    return None
            # Prefix completion on known vocab
            for w in self._vocab:
                wl = w.lower()
                if wl.startswith(lower):
                    remainder = w[len(text) :]
                    if remainder:
                        return Suggestion(remainder)
                    return None
            # Otherwise, hint at creation inline (non-invasive)
            if self._allow_create:
                return Suggestion(f"  [Create '{text}'?]")
            return None

    auto_suggest = _SuggestOrCreate(words, allow_create)

    kb = KeyBindings()
    _menu_opened = False
    _menu_index = 0
    # Enable first-keystroke replace behavior only when a non-empty default is provided.
    replace_mode = bool(default and isinstance(default, str) and default != "")

    @kb.add("down", eager=True)
    def _(event) -> None:  # pragma: no cover - integration path
        nonlocal _menu_opened, _menu_index, replace_mode
        b = event.app.current_buffer
        replace_mode = False
        if b.complete_state is None:
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
    def _(event) -> None:  # pragma: no cover
        nonlocal _menu_opened, _menu_index, replace_mode
        b = event.app.current_buffer
        replace_mode = False
        s = getattr(b, "suggestion", None)
        suggestion_text = getattr(s, "text", None)
        # Ignore creation affordance which starts with two spaces
        if suggestion_text and suggestion_text.startswith("  [Create "):
            suggestion_text = None
        if not suggestion_text:
            cand = _best_prefix_match(b.document.text)
            if cand:
                suggestion_text = cand[len(b.document.text) :]
        if suggestion_text:
            b.insert_text(suggestion_text)
        else:
            if b.complete_state is None:
                b.start_completion(select_first=True)
                _menu_opened = True
                _menu_index = 0
            else:
                b.complete_next()
                _menu_opened = True
                _menu_index += 1

    @kb.add("enter", eager=True)
    def _(event) -> None:  # pragma: no cover
        nonlocal _menu_opened, _menu_index
        b = event.app.current_buffer
        cs = b.complete_state
        if cs is not None and cs.current_completion is not None:
            b.apply_completion(cs.current_completion)
            event.app.current_buffer.validate_and_handle()
            return
        # Apply inline category prefix suggestion (skip creation affordance)
        s = getattr(b, "suggestion", None)
        suggestion_text = getattr(s, "text", None)
        # If no visible suggestion, compute a prefix completion as a fallback
        # so Enter behaves like the legacy selector in headless environments.
        if not suggestion_text:
            cand = _best_prefix_match(b.document.text)
            if cand:
                suggestion_text = cand[len(b.document.text) :]
        if suggestion_text and not suggestion_text.startswith("  [Create "):
            b.insert_text(suggestion_text)
            event.app.current_buffer.validate_and_handle()
            return
        # Fallback commit
        if _menu_opened and not b.document.text:
            idx = max(0, min(_menu_index, len(words) - 1))
            b.insert_text(words[idx])
            event.app.current_buffer.validate_and_handle()
            return
        event.app.current_buffer.validate_and_handle()

    style = Style.from_dict({"auto-suggestion": "fg:#888888"})

    if session is None:
        sess: PromptSession = PromptSession(key_bindings=kb)
    else:
        sess = PromptSession(
            input=getattr(session, "input", None),
            output=getattr(session, "output", None),
            key_bindings=kb,
        )

    # First‑keystroke behavior with a pre-filled default value
    # -------------------------------------------------------
    # Requirements (issue #81):
    # - Cursor should start after the last character of the initial suggestion.
    # - On the first keystroke:
    #     * Backspace or Space: build on the suggestion (standard edit/insert).
    #     * Any other printable character: replace the entire suggestion with that char.
    # - After any navigation/editing (Left/Right/Home/End/Delete/Ctrl-A/Ctrl-E),
    #   future typing should behave normally (no wholesale replace).

    @kb.add("backspace", eager=True)
    def _(event) -> None:  # pragma: no cover
        nonlocal replace_mode
        b = event.app.current_buffer
        # Backspace always deletes a char; on first backspace we just flip the mode.
        b.delete_before_cursor(1)
        replace_mode = False

    # Navigation/editing keys disable replace mode and perform the usual action.
    @kb.add("left", eager=True)
    def _(event) -> None:  # pragma: no cover
        nonlocal replace_mode
        replace_mode = False
        event.app.current_buffer.cursor_left(1)

    @kb.add("right", eager=True)
    def _(event) -> None:  # pragma: no cover
        nonlocal replace_mode
        replace_mode = False
        event.app.current_buffer.cursor_right(1)

    @kb.add("home", eager=True)
    def _(event) -> None:  # pragma: no cover
        nonlocal replace_mode
        replace_mode = False
        event.app.current_buffer.cursor_home()

    @kb.add("end", eager=True)
    def _(event) -> None:  # pragma: no cover
        nonlocal replace_mode
        replace_mode = False
        event.app.current_buffer.cursor_end()

    @kb.add("delete", eager=True)
    def _(event) -> None:  # pragma: no cover
        nonlocal replace_mode
        replace_mode = False
        event.app.current_buffer.delete(1)

    @kb.add("c-a", eager=True)
    def _(event) -> None:  # pragma: no cover
        nonlocal replace_mode
        replace_mode = False
        event.app.current_buffer.cursor_home()

    @kb.add("c-e", eager=True)
    def _(event) -> None:  # pragma: no cover
        nonlocal replace_mode
        replace_mode = False
        event.app.current_buffer.cursor_end()

    # Printable characters: intercept only while in replace mode so we don't
    # duplicate default insertion behavior after the first keystroke.
    @kb.add(Keys.Any, filter=Condition(lambda: replace_mode), eager=True)
    def _(event) -> None:  # pragma: no cover
        nonlocal replace_mode
        data = getattr(event, "data", "") or ""
        # Only act on printable characters; let control/meta fall through.
        if not data or not data.isprintable():
            return
        b = event.app.current_buffer
        if data == " ":
            # Build on the suggestion by inserting a space.
            b.insert_text(" ")
            replace_mode = False
            return
        # Replace entire suggestion with the first character typed.
        b.delete_before_cursor(len(b.document.text_before_cursor))
        b.delete(len(b.document.text_after_cursor))
        b.insert_text(data)
        replace_mode = False

    # Compose prompt kwargs with a real default so the cursor is at the end.
    prompt_kwargs: dict[str, Any] = {
        "message": message,
        "completer": completer,
        "default": default if isinstance(default, str) else "",
        "key_bindings": kb,
        "auto_suggest": auto_suggest,
        "style": style,
    }

    result = sess.prompt(**prompt_kwargs)

    # Interpret result
    # Empty input (e.g., immediate Enter) accepts the proposed default.
    # This path remains for safety, though with a pre-filled default the buffer
    # won't be empty under normal interactive use.
    if result == "":
        result = default if isinstance(default, str) and default != "" else ""
    if allow_create:
        if result == CREATE_SENTINEL:
            return CreateCategoryRequest("")
        if result.lower() not in lower_set:
            # Treat any non-existent entry as a creation intent
            return CreateCategoryRequest(result)
    return result


def prompt_new_category_name(
    *,
    initial: str = "",
    session: PromptSession | None = None,
    message: str = "New category name (Enter to save • Esc or Ctrl+C to cancel): ",
    error_prefix: str = "",
) -> str | None:
    """Collect a new category name with inline validation.

    Returns the saved name, or ``None`` when canceled via Esc or Ctrl+C.
    """

    kb = KeyBindings()

    @kb.add("escape")
    def _(event) -> None:  # pragma: no cover - exercised indirectly
        event.app.exit(result=None)

    # Provide an unambiguous cancel shortcut as well.
    @kb.add("c-c", eager=True)
    def _(event) -> None:  # pragma: no cover - exercised indirectly
        event.app.exit(result=None)

    class _V(Validator):
        def validate(self, document) -> None:
            v = _validate_name(document.text)
            if not getattr(v, "ok", True):
                raise ValidationError(message=(error_prefix + (v.reason or "Invalid name")))

    if session is None:
        sess: PromptSession = PromptSession(key_bindings=kb)
    else:
        sess = PromptSession(
            input=getattr(session, "input", None),
            output=getattr(session, "output", None),
            key_bindings=kb,
        )

    return sess.prompt(
        message,
        default=initial,
        validator=_V(),
        validate_while_typing=False,
        key_bindings=kb,
    )


TOP_LEVEL_SENTINEL = "— Create as top-level —"


def prompt_select_parent(
    parents: Sequence[str],
    *,
    session: PromptSession | None = None,
    message: str = "Choose parent (or '— Create as top-level —'): ",
) -> str | None:
    """Prompt for a parent category among the provided names.

    Returns the chosen parent name, or ``TOP_LEVEL_SENTINEL`` to indicate a
    top-level category. Esc cancels and returns ``None``.
    """

    kb = KeyBindings()

    @kb.add("escape")
    def _(event) -> None:  # pragma: no cover - exercised indirectly
        event.app.exit(result=None)

    words = [TOP_LEVEL_SENTINEL] + list(parents)
    # Map lowercased input to canonical option values for normalization
    canonical = {w.lower(): w for w in words}
    allowed_lower = set(canonical.keys())
    completer = WordCompleter(words, ignore_case=True, match_middle=True, sentence=False)

    class _ParentValidator(Validator):
        def __init__(self, allowed_lower: set[str]) -> None:
            self._allowed_lower = allowed_lower

        def validate(self, document) -> None:
            if document.text.lower() not in self._allowed_lower:
                raise ValidationError(
                    message="Select a parent from the list or keep the top-level option."
                )

    if session is None:
        sess: PromptSession = PromptSession(key_bindings=kb)
    else:
        sess = PromptSession(
            input=getattr(session, "input", None),
            output=getattr(session, "output", None),
            key_bindings=kb,
        )

    value = sess.prompt(
        message,
        default=TOP_LEVEL_SENTINEL,
        completer=completer,
        validator=_ParentValidator(allowed_lower),
        validate_while_typing=False,
    )
    # Normalize to the canonical option (including the sentinel)
    return canonical.get(value.lower(), value)


__all__ = [
    "select_category_or_create",
    "prompt_new_category_name",
    "prompt_new_display_name",
    "prompt_select_parent",
    "CreateCategoryRequest",
    "CREATE_SENTINEL",
    "TOP_LEVEL_SENTINEL",
]


# ----------------------------------------------------------------------------
# Display-name prompt (optional rename step)
# ----------------------------------------------------------------------------


def prompt_new_display_name(
    *,
    initial: str = "",
    session: PromptSession | None = None,
    message: str = "Rename display name (Enter to keep • Esc to cancel): ",
    error_prefix: str = "",
) -> str | None:
    """Collect an optional human-friendly display name with inline validation.

    Behavior
    --------
    - Esc cancels and returns ``None``.
    - Enter on an empty input keeps the current name and returns an empty string
      (callers typically treat that as "no change").
    - Non-empty values are validated with the same rules as category names
      (letters/numbers/space and ``& - /`` only, 1..64 chars).
    """

    kb = KeyBindings()

    @kb.add("escape")
    def _(event) -> None:  # pragma: no cover - exercised indirectly
        event.app.exit(result=None)

    class _V(Validator):
        def validate(self, document) -> None:
            # Allow empty input to mean "keep" without validation errors
            if not document.text.strip():
                return
            v = _validate_name(document.text)
            if not getattr(v, "ok", True):
                raise ValidationError(message=(error_prefix + (v.reason or "Invalid name")))

    if session is None:
        sess: PromptSession = PromptSession(key_bindings=kb)
    else:
        sess = PromptSession(
            input=getattr(session, "input", None),
            output=getattr(session, "output", None),
            key_bindings=kb,
        )

    return sess.prompt(message, default=initial, validator=_V(), validate_while_typing=False)
