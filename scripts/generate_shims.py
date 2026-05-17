#!/usr/bin/env python3
"""Generate legacy shim modules from autoplay_sdk.compat.shims.SHIM_MAP."""

from __future__ import annotations

from pathlib import Path

from autoplay_sdk.compat.shims import SHIM_MAP

TEMPLATE = '''"""Compatibility shim for autoplay-sdk 0.7.4 transition release."""

import importlib
import sys as _sys
import warnings as _warnings

_warnings.warn(
    "`{old}` has moved to `{new}`. "
    "Update your imports before 1.0.0, when the old path will be removed.",
    DeprecationWarning,
    stacklevel=2,
)

_mod = importlib.import_module("{new}")

# Preserve legacy import path, but alias to the canonical module object so
# attribute reads/writes and module globals behave identically.
_sys.modules[__name__] = _mod
globals().update(_mod.__dict__)
'''


def module_to_path(module: str) -> Path:
    assert module.startswith("autoplay_sdk.")
    rel = module.removeprefix("autoplay_sdk.").replace(".", "/")
    if rel in {"serve", "proactive_triggers", "rag_query"}:
        return Path("autoplay_sdk") / rel / "__init__.py"
    if rel in {"proactive_resilience", "agent_states", "agent_state_v2"}:
        return Path("autoplay_sdk") / rel / "__init__.py"
    return Path("autoplay_sdk") / f"{rel}.py"


if __name__ == "__main__":
    for entry in SHIM_MAP:
        old = entry["old_module"]
        new = entry["new_module"]
        path = module_to_path(old)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(TEMPLATE.format(old=old, new=new), encoding="utf-8")
        print(f"wrote {path}")
