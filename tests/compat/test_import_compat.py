from __future__ import annotations

import importlib
import sys
import warnings


def test_rag_alias_imports_without_warning() -> None:
    """`autoplay_sdk.rag` stays a stable alias."""
    sys.modules.pop("autoplay_sdk.rag", None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        mod = importlib.import_module("autoplay_sdk.rag")
    dep = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert not dep
    assert hasattr(mod, "RagPipeline")


def test_top_level_exports_import_cleanly() -> None:
    sys.modules.pop("autoplay_sdk", None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        import autoplay_sdk
    dep = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert not dep
    for name in autoplay_sdk.__all__:
        assert hasattr(autoplay_sdk, name)
