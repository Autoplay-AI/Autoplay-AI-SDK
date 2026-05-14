"""Match inbound Messenger text to quick-reply chip labels (strip + casefold)."""

from __future__ import annotations

from collections.abc import Sequence


def match_quick_reply_label(user_message: str, labels: Sequence[str]) -> int | None:
    """Return the index of the first label equal to the message (strip + casefold), else None."""
    msg = (user_message or "").strip().casefold()
    if not msg:
        return None
    for i, label in enumerate(labels):
        if (label or "").strip().casefold() == msg:
            return i
    return None


def messages_match_quick_reply_pair(
    user_message: str,
    *,
    yes_label: str = "Yes",
    no_label: str = "No",
) -> str | None:
    """Return ``\"yes\"`` or ``\"no\"`` when the message matches labels; else None."""
    msg = (user_message or "").strip().casefold()
    if not msg:
        return None
    if (yes_label or "").strip().casefold() == msg:
        return "yes"
    if (no_label or "").strip().casefold() == msg:
        return "no"
    return None
