from __future__ import annotations

import importlib
import sys
import warnings

import pytest

from autoplay_sdk.compat.shims import SHIM_MAP


@pytest.mark.parametrize(
    "old_module,new_module",
    [(e["old_module"], e["new_module"]) for e in SHIM_MAP],
    ids=[e["old_module"] for e in SHIM_MAP],
)
def test_old_path_imports_with_warning(old_module: str, new_module: str) -> None:
    sys.modules.pop(old_module, None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.import_module(old_module)
    dep = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert dep, f"Expected warning for {old_module}"
    assert new_module in str(dep[0].message)


@pytest.mark.parametrize(
    "old_module,new_module",
    [(e["old_module"], e["new_module"]) for e in SHIM_MAP],
    ids=[e["new_module"] for e in SHIM_MAP],
)
def test_new_path_imports_without_warning(old_module: str, new_module: str) -> None:
    # Never evict canonical modules here; doing so can desync class identity
    # for already-imported references elsewhere in the same test session.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.import_module(new_module)
    offending = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert not offending, (
        f"Unexpected warning importing {new_module}: {[str(w.message) for w in offending]}"
    )


@pytest.mark.parametrize(
    "old_module,new_module",
    [(e["old_module"], e["new_module"]) for e in SHIM_MAP],
    ids=[f"parity:{e['old_module']}" for e in SHIM_MAP],
)
def test_symbol_reachable_via_old_path(old_module: str, new_module: str) -> None:
    """Every public symbol exposed on the new module is reachable on the old path."""
    sys.modules.pop(old_module, None)

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        old_mod = importlib.import_module(old_module)
    new_mod = importlib.import_module(new_module)

    for name in dir(new_mod):
        if name.startswith("_"):
            continue
        assert hasattr(old_mod, name), (
            f"{old_module} shim is missing symbol {name} from {new_module}"
        )


def test_rag_alias_imports_without_warning() -> None:
    """`autoplay_sdk.rag` stays a stable alias during 0.7.4."""
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
