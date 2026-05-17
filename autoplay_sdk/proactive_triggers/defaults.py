"""Compatibility shim for autoplay-sdk 0.7.4 transition release."""

from __future__ import annotations

import importlib.util
import sys as _sys
import warnings as _warnings
from pathlib import Path

_warnings.warn(
    "`autoplay_sdk.proactive.triggers.defaults` has moved to `autoplay_sdk.proactive.triggers.defaults`. "
    "Update your imports before 1.0.0, when the old path will be removed.",
    DeprecationWarning,
    stacklevel=2,
)

# Load canonical defaults by file path to avoid importing
# autoplay_sdk.proactive.triggers.__init__ during partially initialized cycles.
_canonical_path = (
    Path(__file__).resolve().parents[1] / "proactive" / "triggers" / "defaults.py"
)
_module_name = "autoplay_sdk._compat_proactive_defaults"
_spec = importlib.util.spec_from_file_location(_module_name, _canonical_path)
if _spec is None or _spec.loader is None:
    raise ImportError(
        f"Unable to load canonical defaults module from {_canonical_path}"
    )
_mod = importlib.util.module_from_spec(_spec)
_sys.modules[_module_name] = _mod
_spec.loader.exec_module(_mod)

_sys.modules[__name__] = _mod
globals().update(_mod.__dict__)
