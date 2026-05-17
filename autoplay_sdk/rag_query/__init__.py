"""Compatibility shim for autoplay-sdk 0.7.4 transition release."""

import importlib
import warnings as _warnings

_warnings.warn(
    "`autoplay_sdk.rag_query` has moved to `autoplay_sdk.rag.query`. "
    "Update your imports before 1.0.0, when the old path will be removed.",
    DeprecationWarning,
    stacklevel=2,
)

_TARGET = "autoplay_sdk.rag.query"


def __getattr__(name: str):
    mod = importlib.import_module(_TARGET)
    try:
        return getattr(mod, name)
    except AttributeError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc


def __dir__():
    return dir(importlib.import_module(_TARGET))
