#!/usr/bin/env python3
"""Sync autoplay_sdk/skills/*/SKILL.md into Mintlify docs for view + download."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_install_spec = importlib.util.spec_from_file_location(
    "install_skills",
    ROOT / "autoplay_sdk" / "install_skills.py",
)
_install_mod = importlib.util.module_from_spec(_install_spec)
assert _install_spec.loader is not None
_install_spec.loader.exec_module(_install_mod)

ACTIVITY_SKILLS = _install_mod.ACTIVITY_SKILLS
CHATBOT_SKILLS = _install_mod.CHATBOT_SKILLS
CORE_SKILL = _install_mod.CORE_SKILL
MIGRATION_SKILL = _install_mod.MIGRATION_SKILL
SKILLS_ROOT = ROOT / "autoplay_sdk" / "skills"
DOCS_ROOT = ROOT / "docs"
MDX_DIR = DOCS_ROOT / "get-started" / "agent-skills"
DOWNLOAD_DIR = DOCS_ROOT / "files" / "skills"
# Mintlify scans .yaml for OpenAPI; raw SKILL.md is not valid YAML. Use .txt for static downloads.
DOWNLOAD_EXT = ".txt"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def all_skill_dirs() -> list[str]:
    """Return ordered unique skill directory names shipped with the SDK."""
    seen: set[str] = set()
    ordered: list[str] = []

    def add(name: str) -> None:
        if name not in seen:
            seen.add(name)
            ordered.append(name)

    add(CORE_SKILL)
    add(MIGRATION_SKILL)
    for name in sorted(CHATBOT_SKILLS.values()):
        add(name)
    for name in sorted(ACTIVITY_SKILLS.values()):
        add(name)
    return ordered


def parse_skill_md(text: str) -> tuple[dict[str, str], str]:
    """Split SKILL.md into YAML frontmatter fields and markdown body."""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    raw_yaml = match.group(1)
    body = text[match.end() :]
    fields: dict[str, str] = {}
    current_key: str | None = None
    for line in raw_yaml.splitlines():
        if line.startswith("  ") and current_key is not None:
            stripped = line.strip()
            if stripped.startswith(">-") or stripped.startswith("|"):
                continue
            fields[current_key] += " " + stripped
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            current_key = key.strip()
            value = value.strip()
            if value in {">-", "|", ">|-", "|-"}:
                fields[current_key] = ""
            else:
                fields[current_key] = value.strip("'\"")
    return fields, body.lstrip("\n")


def normalize_description(description: str) -> str:
    """Collapse whitespace for safe single-line MDX frontmatter."""
    return re.sub(r"\s+", " ", description).strip()


def yaml_escape(value: str) -> str:
    """Escape a string for a double-quoted YAML value in MDX frontmatter."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def title_from_skill(skill_dir: str, fields: dict[str, str]) -> str:
    name = fields.get("name", skill_dir)
    return name.replace("-", " ").replace("_", " ").title()


def build_mdx(skill_dir: str, fields: dict[str, str], body: str) -> str:
    title = title_from_skill(skill_dir, fields)
    description = normalize_description(
        fields.get("description", f"Autoplay agent skill: {skill_dir}")
    )
    sidebar = skill_dir.replace("-", " ").title()

    return (
        "---\n"
        f'title: "{yaml_escape(title)}"\n'
        f'sidebarTitle: "{yaml_escape(sidebar)}"\n'
        f'description: "{yaml_escape(description)}"\n'
        "---\n\n"
        "<Note>\n"
        "  Auto-generated from `autoplay_sdk/skills/`. "
        "Edit the source `SKILL.md` and run `python scripts/sync_skill_docs.py`.\n"
        "</Note>\n\n"
        f'<a href="/files/skills/{skill_dir}{DOWNLOAD_EXT}" download="SKILL.md"><strong>Download `.md`</strong></a>'
        f' · <a href="/files/skills/{skill_dir}{DOWNLOAD_EXT}" target="_blank"><strong>Open raw file</strong></a>'
        f" · Install via CLI: `autoplay-install-skills`\n\n"
        f"{body.rstrip()}\n"
    )


def sync_skill(skill_dir: str) -> None:
    source = SKILLS_ROOT / skill_dir / "SKILL.md"
    if not source.exists():
        raise FileNotFoundError(f"Missing skill source: {source}")

    raw = source.read_text(encoding="utf-8")
    fields, body = parse_skill_md(raw)

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    MDX_DIR.mkdir(parents=True, exist_ok=True)

    (DOWNLOAD_DIR / f"{skill_dir}{DOWNLOAD_EXT}").write_text(raw, encoding="utf-8")
    for stale in (
        DOWNLOAD_DIR / f"{skill_dir}.md",
        DOWNLOAD_DIR / f"{skill_dir}.yaml",
    ):
        if stale.exists():
            stale.unlink()
    mdx_path = MDX_DIR / f"{skill_dir}.mdx"
    mdx_path.write_text(build_mdx(skill_dir, fields, body), encoding="utf-8")
    print(f"  synced {skill_dir}")


def main() -> None:
    print(f"Syncing skills from {SKILLS_ROOT}\n")
    for skill_dir in all_skill_dirs():
        sync_skill(skill_dir)
    print(f"\nDone. MDX → {MDX_DIR.relative_to(ROOT)}/")
    print(f"      TXT → {DOWNLOAD_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
