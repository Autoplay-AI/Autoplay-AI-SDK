from __future__ import annotations

import importlib.util
from pathlib import Path


_SDK_DIR = Path(__file__).parent.parent
_SYNC_PATH = _SDK_DIR / "scripts" / "sync_skill_docs.py"

_spec = importlib.util.spec_from_file_location("sync_skill_docs", _SYNC_PATH)
sync_skill_docs = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(sync_skill_docs)


def test_amplitude_uses_specific_activity_install_command() -> None:
    assert (
        sync_skill_docs.human_fetch_command("activity-amplitude")
        == "uvx --from autoplay-sdk autoplay-install-skills --user-activity amplitude"
    )


def test_real_skills_have_required_foundation_frontmatter() -> None:
    for skill_dir in sync_skill_docs.catalog_skill_dirs():
        source = sync_skill_docs.SKILLS_ROOT / skill_dir / "SKILL.md"
        fields, _ = sync_skill_docs.parse_skill_md(source.read_text(encoding="utf-8"))

        for field in sync_skill_docs.REQUIRED_FRONTMATTER:
            assert fields.get(field), f"{skill_dir} missing {field}"
        assert fields["skill"] == skill_dir


def test_skill_card_copy_assumes_existing_customer_stack() -> None:
    fields = {"name": "chatbot-intercom"}
    block = sync_skill_docs.skill_card_block("chatbot-intercom", fields)

    assert not block.startswith("---")
    assert "Install Chatbot Intercom into your project" not in block
    assert "existing Intercom Fin AI support agent setup" in block
    assert 'href="/recipes/intercom-tutorial/step-1-connect-real-time-events"' in block
