"""
CLI command: autoplay-install-skills

Copies Cursor/Claude agent skills from the autoplay-sdk package into the
current project's .cursor/skills/ directory.

Usage:
    autoplay-install-skills                                    # install all skills
    autoplay-install-skills --chatbot ada                      # core + ada only
    autoplay-install-skills --chatbot intercom --user-activity posthog
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Maps CLI names to skill directory names inside autoplay_sdk/skills/
CHATBOT_SKILLS: dict[str, str] = {
    "ada": "chatbot-ada",
    "intercom": "chatbot-intercom",
    "botpress": "chatbot-botpress",
    "dify": "chatbot-dify",
    "crisp": "chatbot-crisp",
    "landbot": "chatbot-landbot",
    "tidio": "chatbot-tidio",
}

ACTIVITY_SKILLS: dict[str, str] = {
    "fullstory": "activity-fullstory",
    "posthog": "activity-posthog",
}

CORE_SKILL = "autoplay-core"


def _skills_source_root() -> Path:
    """Return the path to autoplay_sdk/skills/ inside the installed package."""
    # Use __file__-based fallback (works for editable installs and wheels)
    try:
        import autoplay_sdk

        return Path(autoplay_sdk.__file__).parent / "skills"
    except Exception:
        raise RuntimeError(
            "Could not locate autoplay_sdk/skills/ in installed package."
        )


def _copy_skill(source_root: Path, skill_dir_name: str, dest_root: Path) -> bool:
    """Copy a single skill directory to dest_root. Returns True if copied."""
    src = source_root / skill_dir_name
    if not src.exists():
        print(f"  [skip] {skill_dir_name} — not found in package", file=sys.stderr)
        return False
    dest = dest_root / skill_dir_name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    print(f"  ✓ {skill_dir_name}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="autoplay-install-skills",
        description=(
            "Install Autoplay Cursor/Claude agent skills into .cursor/skills/ "
            "in the current directory."
        ),
    )
    parser.add_argument(
        "--chatbot",
        metavar="NAME",
        help=f"Chatbot to install skills for. Choices: {', '.join(CHATBOT_SKILLS)}",
    )
    parser.add_argument(
        "--user-activity",
        metavar="NAME",
        dest="activity",
        help=f"User activity source to install skills for. Choices: {', '.join(ACTIVITY_SKILLS)}",
    )
    parser.add_argument(
        "--dest",
        metavar="DIR",
        default=".cursor/skills",
        help="Destination directory (default: .cursor/skills)",
    )
    args = parser.parse_args()

    # Validate
    if args.chatbot and args.chatbot not in CHATBOT_SKILLS:
        print(
            f"Unknown chatbot '{args.chatbot}'. "
            f"Valid options: {', '.join(CHATBOT_SKILLS)}",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.activity and args.activity not in ACTIVITY_SKILLS:
        print(
            f"Unknown user activity source '{args.activity}'. "
            f"Valid options: {', '.join(ACTIVITY_SKILLS)}",
            file=sys.stderr,
        )
        sys.exit(1)

    source_root = _skills_source_root()
    dest_root = Path(args.dest)
    dest_root.mkdir(parents=True, exist_ok=True)

    print(f"Installing Autoplay skills to {dest_root}/\n")

    # Always install the core skill
    _copy_skill(source_root, CORE_SKILL, dest_root)

    if args.chatbot:
        _copy_skill(source_root, CHATBOT_SKILLS[args.chatbot], dest_root)
    elif args.activity:
        pass  # activity-only install: core + activity below
    else:
        # No filters — install everything
        for skill_dir in CHATBOT_SKILLS.values():
            _copy_skill(source_root, skill_dir, dest_root)
        for skill_dir in ACTIVITY_SKILLS.values():
            _copy_skill(source_root, skill_dir, dest_root)

    if args.activity:
        _copy_skill(source_root, ACTIVITY_SKILLS[args.activity], dest_root)
    elif not args.chatbot and args.chatbot is None:
        pass  # already installed all above

    print(
        "\nDone. Open Cursor or Claude and say:\n"
        '  "Set up Autoplay'
        + (f" with {args.chatbot}" if args.chatbot else "")
        + (f" and {args.activity} for user activity" if args.activity else "")
        + '"\n'
        "The agent will follow the correct wiring pattern automatically."
    )


if __name__ == "__main__":
    main()
