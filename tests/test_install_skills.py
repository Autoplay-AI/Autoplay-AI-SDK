from __future__ import annotations

import sys
from pathlib import Path

_SDK_DIR = Path(__file__).parent.parent / "src" / "customer_sdk"
sys.path.insert(0, str(_SDK_DIR))

from autoplay_sdk.install_skills import _copy_skill  # noqa: E402


def test_copy_skill_preserves_existing_destination_without_force(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    (source_root / "autoplay-core").mkdir(parents=True)
    (source_root / "autoplay-core" / "SKILL.md").write_text("new", encoding="utf-8")
    (dest_root / "autoplay-core").mkdir(parents=True)
    (dest_root / "autoplay-core" / "SKILL.md").write_text("old", encoding="utf-8")

    copied = _copy_skill(source_root, "autoplay-core", dest_root, force=False)

    assert copied is False
    assert (dest_root / "autoplay-core" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "old"


def test_copy_skill_overwrites_existing_destination_with_force(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    (source_root / "autoplay-core").mkdir(parents=True)
    (source_root / "autoplay-core" / "SKILL.md").write_text("new", encoding="utf-8")
    (dest_root / "autoplay-core").mkdir(parents=True)
    (dest_root / "autoplay-core" / "SKILL.md").write_text("old", encoding="utf-8")

    copied = _copy_skill(source_root, "autoplay-core", dest_root, force=True)

    assert copied is True
    assert (dest_root / "autoplay-core" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "new"
