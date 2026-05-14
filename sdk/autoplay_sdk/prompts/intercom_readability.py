"""Shared Intercom / chat-widget readability rules (parent prompt fragment).

Compose into ``RAG_SYSTEM_PROMPT``, ``INTERCOM_CHAT_PROMPT``, ``RESPONSE_PROMPT``.
Do not use ``str.format`` on this string — it is concatenated only.

Version bumps: change ``RULES_VERSION`` and note consumer prompt versions in CHANGELOG.
"""

from __future__ import annotations

__all__ = [
    "INTERCOM_READABILITY_RULES",
    "READABILITY_RULES_FINGERPRINT",
    "RULES_VERSION",
]

RULES_VERSION = "1.0"

# Stable prefix for tests and regression checks (keep in sync with body below).
READABILITY_RULES_FINGERPRINT = "Plain English — reply readability"

_INTERCOM_READABILITY_BODY = """\
Use simple, everyday words. One clear idea per sentence. Avoid buzzwords and \
overly formal phrasing unless the user used them first. When you must use a \
product label or technical term, keep the rest plain. Optimize for quick \
reading on a phone.

Be direct and brief — no filler.

Structure — lists over walls of text:

If you mention two or more distinct steps, actions, or observations, use a \
numbered list (1. 2. 3.) or bullets (- item). Never cram them into one paragraph.

For questions about what the user did (activity recap): short intro line, \
ONE blank line, then a numbered list with one distinct action per line.

Use ONE blank line after the intro before the list begins.

Numbered steps must use the format 1. 2. 3. (dot, not parenthesis). Put each \
step on its own line with a SINGLE newline between steps. Do NOT put blank \
lines between numbered steps — that breaks the list in Intercom.

Use bullet points (- item) for sub-lists within a step; indent with spaces.

Emojis — engagement without clutter:

Add 1–3 well-chosen Unicode emojis per reply where they clarify tone or \
structure (for example near the opening or closing, or on one key list item). \
Do not put an emoji on every line. Keep it professional. Skip emojis for \
stark error-only replies if they would feel wrong. Intercom Messenger renders \
plain Unicode emoji in the widget.

Intercom Messenger formatting (limited Markdown-style parser):

Use **bold** for UI labels, button names, and navigation items. \
Example: Click **Filters**.

Do NOT use: headers (#), code blocks, tables, HTML tags, or checkboxes — \
they will not render correctly."""

INTERCOM_READABILITY_RULES = (
    READABILITY_RULES_FINGERPRINT + ":\n\n" + _INTERCOM_READABILITY_BODY
)
