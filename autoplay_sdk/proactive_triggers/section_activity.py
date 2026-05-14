"""Product section playbook — URL-derived section metrics for proactive triggers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from autoplay_sdk.models import SlimAction

_DEFAULT_UNMAPPED_SECTION_ID = "other"


def resolve_section_id(
    canonical_url: str,
    rules: Sequence[Mapping[str, Any]],
) -> str | None:
    """Map ``canonical_url`` to ``section_id`` using ordered prefix rules.

    First matching rule wins. Comparison uses ``str.startswith`` on the stripped
    canonical URL (no automatic slash normalization — prefixes must match wire format).
    """
    u = (canonical_url or "").strip()
    if not u:
        return None
    for rule in rules:
        pfx = (rule.get("prefix") or "").strip()
        sid = (rule.get("section_id") or "").strip()
        if not pfx or not sid:
            continue
        if u.startswith(pfx):
            return sid
    return None


def _effective_section_id(
    canonical_url: str,
    rules: Sequence[Mapping[str, Any]],
    fallback_id: str | None,
) -> str:
    rid = resolve_section_id(canonical_url, rules)
    if rid is not None:
        return rid
    if fallback_id is not None and str(fallback_id).strip():
        return str(fallback_id).strip()
    return _DEFAULT_UNMAPPED_SECTION_ID


def iso8601_utc_z(ts: float) -> str:
    """Format unix timestamp as ISO 8601 UTC with ``Z`` suffix (no subseconds)."""
    dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def total_dwell_seconds(section: Mapping[str, Any]) -> float:
    """Sum ``dwell_seconds_per_visit`` for one section entry."""
    raw = section.get("dwell_seconds_per_visit")
    if not isinstance(raw, list):
        return 0.0
    return float(sum(float(x) for x in raw))


def top_playbook_section_id(
    product_section_playbook: Mapping[str, Any],
    section_playbook: Mapping[str, Any],
) -> str | None:
    """Pick section id maximizing total dwell among keys present in both maps."""
    if not isinstance(product_section_playbook, Mapping) or not isinstance(
        section_playbook, Mapping
    ):
        return None
    psp_sections = product_section_playbook.get("sections")
    if not isinstance(psp_sections, dict) or not psp_sections:
        return None
    candidates: list[tuple[str, float, int]] = []
    for sid, stats in psp_sections.items():
        if sid not in section_playbook:
            continue
        if not isinstance(stats, Mapping):
            continue
        vc = int(stats.get("visit_count") or 0)
        td = total_dwell_seconds(stats)
        candidates.append((sid, td, vc))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (-t[1], -t[2], t[0]))
    return candidates[0][0]


def build_product_section_playbook(
    actions: Sequence[SlimAction],
    *,
    rules: Sequence[Mapping[str, Any]],
    fallback_id: str | None = None,
) -> dict[str, Any]:
    """Build ``context_extra.product_section_playbook`` from recent actions.

    Per-section visit lists reset when the user navigates away and returns (global
    section id changes between consecutive actions).

    Dwell per action: ``max(0, timestamp_end - timestamp_start)``.
    """
    if not rules:
        return {"runtime": {"current_section_id": ""}, "sections": {}}

    # Per section: visits list (dwell totals), first/last timestamps across window.
    state: dict[str, dict[str, Any]] = {}
    prev: str | None = None

    for a in actions:
        sid = _effective_section_id(a.canonical_url, rules, fallback_id)
        dwell = max(0.0, float(a.timestamp_end) - float(a.timestamp_start))
        ts0 = float(a.timestamp_start)
        ts1 = float(a.timestamp_end)

        if sid not in state:
            state[sid] = {
                "visits": [dwell],
                "first_ts": ts0,
                "last_ts": ts1,
            }
            prev = sid
            continue

        if sid == prev:
            state[sid]["visits"][-1] += dwell
            state[sid]["first_ts"] = min(float(state[sid]["first_ts"]), ts0)
            state[sid]["last_ts"] = max(float(state[sid]["last_ts"]), ts1)
        else:
            state[sid]["visits"].append(dwell)
            state[sid]["first_ts"] = min(float(state[sid]["first_ts"]), ts0)
            state[sid]["last_ts"] = max(float(state[sid]["last_ts"]), ts1)
        prev = sid

    runtime_id = ""
    if actions:
        runtime_id = _effective_section_id(
            actions[-1].canonical_url, rules, fallback_id
        )

    sections_out: dict[str, Any] = {}
    for sid, blob in state.items():
        visits_raw = blob["visits"]
        visits = [float(v) for v in visits_raw]
        sections_out[sid] = {
            "visit_count": len(visits),
            "dwell_seconds_per_visit": visits,
            "first_visited_at": iso8601_utc_z(float(blob["first_ts"])),
            "last_visited_at": iso8601_utc_z(float(blob["last_ts"])),
        }

    return {
        "runtime": {"current_section_id": runtime_id},
        "sections": sections_out,
    }


def resolve_section_id_for_playbook(
    context_extra: Mapping[str, Any],
) -> str | None:
    """Effective playbook row id: host override, then ranked metrics, then runtime."""
    book = context_extra.get("section_playbook")
    if not isinstance(book, dict):
        return None
    cur = (context_extra.get("current_section_id") or "").strip()
    if cur and cur in book:
        return cur

    psp = context_extra.get("product_section_playbook")
    if isinstance(psp, dict):
        tid = top_playbook_section_id(psp, book)
        if tid:
            return tid
        runtime = psp.get("runtime")
        if isinstance(runtime, dict):
            rid = (runtime.get("current_section_id") or "").strip()
            if rid and rid in book:
                return rid
    return None
