"""Minimal interactive category review using prompt_toolkit.

This module implements a simple, keyboard‑only dropdown for confirming or
adjusting a category per transaction. It intentionally avoids any DB
integration and uses the in‑repo allowed category list as the sole source of
options.

Behavior
--------
- On a TTY, show an interactive list (↑/↓ to move, Enter to confirm) with the
  transaction's current category pre‑selected.
- In non‑interactive environments (no TTY) or when ``prompt_toolkit`` is not
  available, skip the UI and keep the pre‑determined category unchanged.

The functions here are designed to be dependency‑light and side‑effect free:
they return updated ``CategorizedTransaction`` items without persisting
anything.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from typing import Any

from .categorization import ALLOWED_CATEGORIES
from .models import CategorizedTransaction


def _is_interactive() -> bool:
    """Return True when both stdin and stdout are attached to a TTY."""

    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:  # pragma: no cover - defensive; very unlikely to fail
        return False


def select_category_dropdown(
    *,
    default_code: str,
    options: Sequence[str] = ALLOWED_CATEGORIES,
    context_line: str | None = None,
) -> str:
    """Render a minimal dropdown and return the chosen category code.

    Navigation is via the up/down arrow keys; Enter confirms the highlighted
    selection. The initial highlight is the ``default_code`` when present in
    ``options``; otherwise the first option.

    When ``prompt_toolkit`` is unavailable or the terminal is not interactive,
    this function returns ``default_code`` unchanged.
    """

    if not _is_interactive():
        return default_code

    try:
        # Defer heavy imports so non‑interactive callers don't pay the cost.
        from prompt_toolkit.application import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import HSplit, Layout
        from prompt_toolkit.widgets import Box, Label, RadioList
    except Exception:
        # Library not installed or terminal initialization failed → fallback
        return default_code

    values = [(code, code) for code in options]
    # RadioList expects a sequence of (value, label); current_value stores the value.
    rl = RadioList(values)

    # Preselect the default when possible
    if default_code in {c for c, _ in values}:
        rl.current_value = default_code
    else:
        rl.current_value = values[0][0]

    kb = KeyBindings()

    @kb.add("enter")
    def _(event: Any) -> None:  # pragma: no cover - interactive
        event.app.exit(result=rl.current_value)

    # Escape/Control‑C keep the default selection
    @kb.add("escape")
    @kb.add("c-c")
    def _cancel(event: Any) -> None:  # pragma: no cover - interactive
        event.app.exit(result=default_code)

    header = "Arrows to navigate • Enter to confirm"
    if context_line:
        header = f"{context_line}\n{header}"

    root_container = Box(
        HSplit(
            [
                Label(text=header),
                rl,
            ]
        ),
        padding=1,
    )

    app: Any = Application(layout=Layout(root_container), key_bindings=kb, full_screen=False)

    try:
        result = app.run()  # blocks until exit() is called by a key binding
    except Exception:
        # Any runtime UI error → stick with the default
        return default_code

    # Sanity: ensure the result is a valid option; otherwise fall back to default
    return result if isinstance(result, str) and result in options else default_code


def review_transaction_categories(
    transactions_with_categories: Iterable[CategorizedTransaction],
    *,
    # These kwargs are accepted for compatibility with the public API but are
    # intentionally unused in this minimal implementation.
    source_provider: str | None = None,  # noqa: ARG001
    source_account: str | None = None,  # noqa: ARG001
    database_url: str | None = None,  # noqa: ARG001
    exemplars: int | None = None,  # noqa: ARG001
) -> list[CategorizedTransaction]:
    """Return reviewed items, optionally updated via a dropdown per transaction.

    - If interactive (TTY + prompt_toolkit available), present a dropdown of
      :data:`ALLOWED_CATEGORIES` per transaction with the current category
      pre‑selected and return the possibly updated list.
    - Otherwise, return the input unchanged.
    """

    items = list(transactions_with_categories)
    if not items or not _is_interactive():
        return items

    reviewed: list[CategorizedTransaction] = []
    for ct in items:
        tx = ct.transaction
        # Optional one‑line context to aid decisions, kept intentionally short.
        date = str(tx.get("date") or "")
        desc = str(tx.get("description") or tx.get("merchant") or "")
        amt = str(tx.get("amount") or "")
        context = " ".join(filter(None, [date, amt, desc[:60]])).strip() or None

        chosen = select_category_dropdown(default_code=ct.category, context_line=context)
        if chosen == ct.category:
            reviewed.append(ct)
        else:
            reviewed.append(CategorizedTransaction(transaction=ct.transaction, category=chosen))

    return reviewed


__all__ = ["select_category_dropdown", "review_transaction_categories"]
