#!/usr/bin/env python3
"""Move helper for autoplay-sdk 0.7.4 domain reorganization."""

from __future__ import annotations

from pathlib import Path

MOVES: list[tuple[str, str]] = [
    ("autoplay_sdk/models.py", "autoplay_sdk/core/models.py"),
    ("autoplay_sdk/exceptions.py", "autoplay_sdk/core/exceptions.py"),
    ("autoplay_sdk/metrics.py", "autoplay_sdk/core/metrics.py"),
    ("autoplay_sdk/chatbot.py", "autoplay_sdk/chat/chatbot.py"),
    ("autoplay_sdk/chat_pipeline.py", "autoplay_sdk/chat/chat_pipeline.py"),
    ("autoplay_sdk/agent_context.py", "autoplay_sdk/context/agent_context.py"),
    ("autoplay_sdk/context_store.py", "autoplay_sdk/context/context_store.py"),
    ("autoplay_sdk/user_index.py", "autoplay_sdk/context/user_index.py"),
    ("autoplay_sdk/summarizer.py", "autoplay_sdk/context/summarizer.py"),
]

if __name__ == "__main__":
    root = Path.cwd()
    print("Planned moves:")
    for old, new in MOVES:
        print(f"  {old} -> {new}")
    print(
        "Use git mv manually when needed; this script is informational and kept for migration traceability."
    )
