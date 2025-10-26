"""Pytest configuration for test isolation.

This repo's categorization pipeline persists per-page caches under a default
project-relative directory (``./.cache``). When tests run in the same working
tree, those cache files can cause cross-test contamination (later tests may
hit a cache written by earlier tests and skip the stubbed OpenAI call paths),
which makes assertions about call counts and error handling flaky.

To keep tests hermetic, we redirect the cache root to a unique temporary
directory for each test via an autouse fixture.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Force a per-test cache root so tests don't share on-disk state.

    The application reads ``FA_CACHE_DIR`` (when set) to override the default
    ``./.cache`` location. We point it at the test's own temporary directory.
    """

    cache_root = tmp_path / "cache"
    # Ensure the directory exists to make behavior explicit and help debugging.
    cache_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FA_CACHE_DIR", os.fspath(cache_root))
