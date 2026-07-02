"""Pure URL-pattern predicates used by proactive triggers.

Extracted from ``autoplay_sdk.integrations.intercom`` to break the circular
import that arose when trigger modules (inside ``autoplay_sdk.proactive``)
imported directly from ``integrations.intercom``, which in turn imports from
``autoplay_sdk.proactive.triggers.defaults``.

``autoplay_sdk.integrations.intercom`` re-exports both functions for backward
compatibility — existing callers are unaffected.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence


def proactive_trigger_canonical_url_ping_pong(
    urls: Sequence[str | None],
    *,
    min_cycles: int = 1,
) -> bool:
    """True when the user oscillates between canonical URLs (A→B→A pattern).

    Drops empty/None entries, then counts overlapping triples where
    ``seq[i] == seq[i+2]`` and ``seq[i] != seq[i+1]`` (same page, different
    page, back to first). Requires ``min_cycles`` such triples (default 1).

    Examples (truthy when ``min_cycles == 1``)::

        /a, /b, /a
        /x, /y, /z, /y, /x  → two overlapping cycles if distinct enough

    Monotonic navigation (only forward) returns False.
    """
    seq = [str(u).strip() for u in urls if u is not None and str(u).strip()]
    if len(seq) < 3:
        return False
    cycles = 0
    for i in range(len(seq) - 2):
        if seq[i] == seq[i + 2] and seq[i] != seq[i + 1]:
            cycles += 1
    return cycles >= min_cycles


def proactive_trigger_url_hesitation(
    urls: Sequence[str | None],
    *,
    min_distinct: int = 3,
    min_repeats: int = 1,
) -> bool:
    """True when the URL sequence shows a hesitation pattern broader than strict ping-pong.

    Catches the very common "tried multiple pages and came back" pattern that
    strict A→B→A misses. Example:

        /a, /b, /c, /a            → tried 3, returned to /a (hesitation)
        /projects, /clients, /projects, /reports, /projects → exploring then returning

    Fires when BOTH of the following hold over the (non-empty, trimmed)
    sequence:

      - distinct URL count ≥ ``min_distinct``  (user looked at ≥N different
        pages — they're shopping around, not just navigating once),
      - at least ``min_repeats`` URLs are visited more than once (user
        returned to something — they didn't find what they wanted on the
        first visit).

    Monotonic forward navigation (``/a, /b, /c, /d, /e``) returns False
    no matter how many pages — that's exploration, not hesitation.
    Same goes for a 2-page back-and-forth (``/a, /b, /a, /b``) which has
    only 2 distinct URLs; the strict ping-pong predicate handles that case
    independently. The two predicates are designed to compose: a trigger
    fires when EITHER one returns True.

    Defaults (3, 1) chosen empirically — looser thresholds fire on noise
    (every navigation triple with one revisit), stricter ones miss the
    common "3 wrong pages then back" struggle pattern.
    """
    seq = [str(u).strip() for u in urls if u is not None and str(u).strip()]
    if len(seq) < 3:
        return False
    if len(set(seq)) < min_distinct:
        return False
    counts = Counter(seq)
    repeats = sum(1 for v in counts.values() if v >= 2)
    return repeats >= min_repeats


def proactive_trigger_canonical_url_ping_pong_projects_either_leg(
    urls: Sequence[str | None],
    *,
    projects_substring: str = "projects",
    min_cycles: int = 1,
) -> bool:
    """A→B→A oscillation where **at least one** of A or B contains ``projects_substring``.

    For each overlapping triple ``(A, B, C)`` with ``A == C`` and ``A != B``,
    counts a cycle only when ``projects_substring`` appears in **A or B**
    (inclusive OR — neither leg is required if the other already qualifies).
    Empty ``projects_substring`` counts every A→B→A triple (same as
    :func:`proactive_trigger_canonical_url_ping_pong`).
    """
    sub = (projects_substring or "").strip()
    seq = [str(u).strip() for u in urls if u is not None and str(u).strip()]
    if len(seq) < 3:
        return False
    cycles = 0
    for i in range(len(seq) - 2):
        a, b, c = seq[i], seq[i + 1], seq[i + 2]
        if a == c and a != b:
            if not sub or (sub in a or sub in b):
                cycles += 1
    return cycles >= min_cycles
