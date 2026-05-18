"""Compatibility shim for autoplay-sdk 0.7.4 transition release."""

import importlib
import sys as _sys
import warnings as _warnings

_warnings.warn(
    "`autoplay_sdk.proactive.triggers.triggers.user_page_dwell` has moved to `autoplay_sdk.proactive.triggers.triggers.user_page_dwell`. "
    "Update your imports before 1.0.0, when the old path will be removed.",
    DeprecationWarning,
    stacklevel=2,
)

_mod = importlib.import_module(
    "autoplay_sdk.proactive.triggers.triggers.user_page_dwell"
)

# Preserve legacy import path, but alias to the canonical module object so
# attribute reads/writes and module globals behave identically.
_sys.modules[__name__] = _mod
globals().update(_mod.__dict__)
