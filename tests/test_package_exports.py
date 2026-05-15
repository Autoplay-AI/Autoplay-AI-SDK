from __future__ import annotations

import sys
from pathlib import Path

_SDK_DIR = Path(__file__).parent.parent / "src" / "customer_sdk"
sys.path.insert(0, str(_SDK_DIR))

import autoplay_sdk  # noqa: E402


def test_agent_state_v2_module_is_exported() -> None:
    assert hasattr(autoplay_sdk, "agent_state_v2")
    assert hasattr(autoplay_sdk.agent_state_v2, "SessionState")


def test_version_is_defined() -> None:
    assert isinstance(autoplay_sdk.__version__, str)
    assert autoplay_sdk.__version__ != ""
