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
# Legacy download location — superseded by docs/<skill_dir>/SKILL.{md,txt},
# same layout as docs/autoplay-agentic-setup/. Only used to clean up stale files.
LEGACY_DOWNLOAD_DIR = DOCS_ROOT / "files" / "skills"
DOCS_BASE_URL = "https://developers.autoplay.ai"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


_CHATBOT_FLAG_BY_DIR = {v: k for k, v in CHATBOT_SKILLS.items()}
_ACTIVITY_FLAG_BY_DIR = {v: k for k, v in ACTIVITY_SKILLS.items()}


def human_fetch_command(skill_dir: str) -> str:
    """The human-facing install command for this skill — runs `autoplay-sdk`
    (already published on PyPI) ephemerally via `uvx`, no `pip install` step
    and no new package to build/publish (unlike an npx-based equivalent,
    which would need a brand-new npm package since nothing Autoplay-related
    exists on the npm registry today)."""
    if skill_dir == CORE_SKILL:
        flag = ""
    elif skill_dir == MIGRATION_SKILL:
        flag = " --migrate"
    elif skill_dir in _CHATBOT_FLAG_BY_DIR:
        flag = f" --chatbot {_CHATBOT_FLAG_BY_DIR[skill_dir]}"
    elif skill_dir in _ACTIVITY_FLAG_BY_DIR:
        flag = f" --user-activity {_ACTIVITY_FLAG_BY_DIR[skill_dir]}"
    else:
        # Not yet wired into install_skills.py's flag maps (e.g. activity-amplitude)
        flag = ""
    return f"uvx --from autoplay-sdk autoplay-install-skills{flag}"


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
    # Shipped under autoplay_sdk/skills/ and already published to docs, but not
    # yet wired into install_skills.py's ACTIVITY_SKILLS map.
    add("activity-amplitude")
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


# Markdown links whose target is skill-local (references/, examples/, …) — i.e.
# not http(s), absolute, anchor, or mailto. Those files ship with the installed
# skill but are NOT published to the docs site, so they'd render as broken links.
_SKILL_LOCAL_LINK_RE = re.compile(r"\[([^\]]+)\]\((?!https?://|/|#|mailto:)[^)]*\)")


def strip_skill_local_links(body: str) -> str:
    """Replace skill-local relative links with their link text (docs-only).

    The raw SKILL.md (the downloadable .txt) keeps the links intact — the
    installed skill has those files. Only the rendered docs page strips them.
    """
    return _SKILL_LOCAL_LINK_RE.sub(r"\1", body)


def normalize_description(description: str) -> str:
    """Collapse whitespace for safe single-line MDX frontmatter."""
    return re.sub(r"\s+", " ", description).strip()


def yaml_escape(value: str) -> str:
    """Escape a string for a double-quoted YAML value in MDX frontmatter."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def title_from_skill(skill_dir: str, fields: dict[str, str]) -> str:
    name = fields.get("name", skill_dir)
    return name.replace("-", " ").replace("_", " ").title()


def frontmatter(skill_dir: str, fields: dict[str, str]) -> str:
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
    )


def build_skill_md(skill_dir: str, fields: dict[str, str], body: str) -> str:
    """Full skill content (frontmatter + body, no Card) — served raw at
    /<skill_dir>/SKILL.md, same as docs/autoplay-agentic-setup/SKILL.md."""
    body = strip_skill_local_links(body)
    return f"{frontmatter(skill_dir, fields)}{body.rstrip()}\n"


def skill_card_block(skill_dir: str, fields: dict[str, str]) -> str:
    """The 'One command' + 'Agent onboarding' CardGroup for this skill.

    Shared by the standalone agent-skills page and by whatever related doc
    it gets embedded into via upsert_skill_card()."""
    title = title_from_skill(skill_dir, fields)
    skill_url = f"{DOCS_BASE_URL}/{skill_dir}/SKILL.md"
    fetch_command = human_fetch_command(skill_dir)

    return (
        f"{frontmatter(skill_dir, fields)}"
        "<Note>\n"
        "  Auto-generated from `autoplay_sdk/skills/`. "
        "Edit the source `SKILL.md` and run `python scripts/sync_skill_docs.py`.\n"
        "</Note>\n\n"
        "## ⚡ Install this skill\n\n"
        "<CardGroup cols={2}>\n\n"
        '<Card title="One command" icon="terminal">\n'
        f"  Install {title} into your project in one step.\n\n"
        "  <CodeGroup>\n\n"
        "```bash CLI\n"
        f"{fetch_command}\n"
        "```\n\n"
        "  </CodeGroup>\n\n"
        '  <a className="skill-card-link" href="/quickstart">View the docs →</a>\n\n'
        "</Card>\n\n"
        '<Card title="Agent onboarding" icon="robot">\n'
        f"  Fetch this skill and start building with {title}.\n\n"
        "  <CodeGroup>\n\n"
        "```bash cURL\n"
        f"curl -s {skill_url}\n"
        "```\n\n"
        "  </CodeGroup>\n\n"
        f'  <a className="skill-card-link" href="{skill_url}" target="_blank">View the skill →</a>\n\n'
        "</Card>\n\n"
        "</CardGroup>\n"
    )


def build_page_mdx(skill_dir: str, fields: dict[str, str]) -> str:
    """Standalone doc page — just the onboarding cards, no skill body.
    Full instructions live in SKILL.md/SKILL.txt, reachable via the agent
    card's View link. Not linked from nav; the same cards are embedded in
    each skill's related doc via upsert_skill_card()."""
    return (
        f"{frontmatter(skill_dir, fields)}"
        "<Note>\n"
        "  Auto-generated from `autoplay_sdk/skills/`. "
        "Edit the source `SKILL.md` and run `python scripts/sync_skill_docs.py`.\n"
        "</Note>\n\n"
        f"{skill_card_block(skill_dir, fields)}"
    )


# Where each skill's onboarding cards get embedded (path under DOCS_ROOT,
# no .mdx extension). These are hand-authored recipe/product pages — only
# the marked block below is managed by this script; the rest is untouched.
RELATED_DOC: dict[str, str] = {
    CORE_SKILL: "quickstart",
    MIGRATION_SKILL: "sdk/migration-0.7.4",
    "chatbot-crisp": "recipes/crisp-ai/step-1-connect-real-time-events",
    "chatbot-dify": "recipes/dify-tutorial/step-1-connect-real-time-events",
    "chatbot-intercom": "recipes/intercom-tutorial/step-1-connect-real-time-events",
    "chatbot-tidio": "recipes/tidio/step-1-connect-real-time-events",
    "chatbot-ada": "recipes/ada/step-1-connect-real-time-events",
    "chatbot-botpress": "recipes/botpress/step-1-connect-real-time-events",
    "chatbot-landbot": "recipes/landbot/step-1-connect-real-time-events",
    "activity-amplitude": "recipes/amplitude/how-to-setup",
    "activity-posthog": "recipes/posthog/how-to-setup",
    "activity-fullstory": "recipes/fullstory/how-to-setup",
}

SKILL_CARD_START = "{/* skill-card:start */}"
SKILL_CARD_END = "{/* skill-card:end */}"
_SKILL_CARD_RE = re.compile(
    re.escape(SKILL_CARD_START) + r".*?" + re.escape(SKILL_CARD_END), re.DOTALL
)


def upsert_skill_card(doc_path: Path, block: str) -> None:
    """Insert or replace the marked skill-card block in a related doc.

    Everything outside the markers is left untouched, so this can re-run
    after a SKILL.md edit without clobbering hand-written page content.
    """
    text = doc_path.read_text(encoding="utf-8")
    marked = f"{SKILL_CARD_START}\n\n{block}\n{SKILL_CARD_END}"

    if _SKILL_CARD_RE.search(text):
        text = _SKILL_CARD_RE.sub(marked, text)
    else:
        match = FRONTMATTER_RE.match(text)
        if not match:
            raise ValueError(f"No frontmatter found in {doc_path}")
        before = text[: match.end()].rstrip("\n")
        after = text[match.end() :].lstrip("\n")
        text = f"{before}\n\n{marked}\n\n{after}"

    doc_path.write_text(text, encoding="utf-8")


def sync_skill(skill_dir: str) -> None:
    source = SKILLS_ROOT / skill_dir / "SKILL.md"
    if not source.exists():
        raise FileNotFoundError(f"Missing skill source: {source}")

    raw = source.read_text(encoding="utf-8")
    fields, body = parse_skill_md(raw)

    MDX_DIR.mkdir(parents=True, exist_ok=True)
    mdx_path = MDX_DIR / f"{skill_dir}.mdx"
    mdx_path.write_text(build_page_mdx(skill_dir, fields), encoding="utf-8")

    # Same layout as docs/autoplay-agentic-setup/: SKILL.txt is the pristine
    # installer source, SKILL.md is the doc-flavored full version — both
    # fetchable raw at /<skill_dir>/SKILL.{txt,md}, no rendered page needed.
    skill_out_dir = DOCS_ROOT / skill_dir
    skill_out_dir.mkdir(parents=True, exist_ok=True)
    (skill_out_dir / "SKILL.txt").write_text(raw, encoding="utf-8")
    (skill_out_dir / "SKILL.md").write_text(
        build_skill_md(skill_dir, fields, body), encoding="utf-8"
    )

    legacy_txt = LEGACY_DOWNLOAD_DIR / f"{skill_dir}.txt"
    if legacy_txt.exists():
        legacy_txt.unlink()

    related = RELATED_DOC.get(skill_dir)
    if related:
        related_path = DOCS_ROOT / f"{related}.mdx"
        if related_path.exists():
            upsert_skill_card(related_path, skill_card_block(skill_dir, fields))
        else:
            print(f"  WARNING: related doc missing for {skill_dir}: {related_path}")

    print(f"  synced {skill_dir}")


def main() -> None:
    print(f"Syncing skills from {SKILLS_ROOT}\n")
    for skill_dir in all_skill_dirs():
        sync_skill(skill_dir)
    print(f"\nDone. MDX  → {MDX_DIR.relative_to(ROOT)}/<skill>.mdx")
    print(f"      SKILL → {DOCS_ROOT.relative_to(ROOT)}/<skill>/SKILL.{{md,txt}}")


if __name__ == "__main__":
    main()
