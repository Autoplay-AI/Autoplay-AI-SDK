"""Shared pytest fixtures for the autoplay SDK test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make autoplay_sdk importable without installing it.
_SDK_DIR = Path(__file__).parent.parent
if str(_SDK_DIR) not in sys.path:
    sys.path.insert(0, str(_SDK_DIR))


@pytest.fixture(autouse=True)
def _clear_autoplay_unkey_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent developer ``AUTOPLAY_APP_UNKEY_TOKEN`` from affecting unrelated tests."""
    monkeypatch.delenv("AUTOPLAY_APP_UNKEY_TOKEN", raising=False)
