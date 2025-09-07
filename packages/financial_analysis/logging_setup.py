"""Centralized logging configuration for the ``financial_analysis`` package.

This module provides two public helpers:

- ``configure_logging(...)``: attach a single ``StreamHandler`` to the package
  root logger (``"financial_analysis"``). Intended to be called once by
  entrypoints (e.g., the CLI) at process startup.
- ``get_logger(name)``: acquire a logger by name, ensuring that the package
  root logger has at least a ``NullHandler`` attached when not configured to
  avoid "No handler" warnings in library contexts.

Library modules must never attach their own handlers. They should only call
``get_logger("financial_analysis.<module>")`` and rely on the centralized
configuration performed by the CLI or host application.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import IO

_PKG_LOGGER_NAME = "financial_analysis"
_CONFIGURED = False


def _parse_level(level: int | str | None) -> int:
    if isinstance(level, int):
        return level
    if isinstance(level, str):
        # Accept numeric strings or standard level names (INFO/DEBUG/etc.).
        level = level.strip().upper()
        if level.isdigit():
            return int(level)
        numeric = getattr(logging, level, None)
        if isinstance(numeric, int):
            return numeric
    # Env override when explicit ``level`` is None
    env_val = os.getenv("FINANCIAL_ANALYSIS_LOG_LEVEL")
    if env_val:
        return _parse_level(env_val)
    return logging.INFO


def configure_logging(
    level: int | str | None = None,
    *,
    fmt: str | None = None,
    stream: IO[str] = sys.stderr,
) -> None:
    """Configure the package root logger exactly once.

    Parameters
    ----------
    level:
        Logging level as ``int`` or level-name string (e.g., ``"INFO"``). If
        ``None``, defaults to the ``FINANCIAL_ANALYSIS_LOG_LEVEL`` environment
        variable when set, otherwise ``logging.INFO``.
    fmt:
        Optional logging format string. Defaults to
        ``"%(asctime)s %(name)s %(levelname)s %(message)s"``.
    stream:
        The output stream for the single ``StreamHandler`` (defaults to
        ``sys.stderr``).
    """

    global _CONFIGURED
    if _CONFIGURED:
        return

    logger = logging.getLogger(_PKG_LOGGER_NAME)

    # Remove any existing NullHandlers to avoid swallowing logs after config.
    for h in list(logger.handlers):
        if isinstance(h, logging.NullHandler):
            logger.removeHandler(h)

    handler = logging.StreamHandler(stream)
    handler.setLevel(_parse_level(level))
    formatter = logging.Formatter(fmt or "%(asctime)s %(name)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)

    logger.setLevel(_parse_level(level))
    logger.addHandler(handler)
    # Avoid double emission via the root logger.
    logger.propagate = False

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger by name, ensuring safe defaults for library use.

    When the central configuration hasn't run yet, attach a ``NullHandler`` to
    the package root logger to avoid noisy warnings. This has no observable
    output and preserves the library-friendly behavior of silent logging until
    an application configures handlers explicitly.
    """

    pkg_logger = logging.getLogger(_PKG_LOGGER_NAME)
    if not _CONFIGURED and not pkg_logger.handlers:
        pkg_logger.addHandler(logging.NullHandler())
    return logging.getLogger(name)
