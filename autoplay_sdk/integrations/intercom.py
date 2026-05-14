"""Intercom integration recipe — webhooks, proactive quick replies, optional connector LLM labels.

Use these constants when configuring Intercom Developer Hub so your subscription
matches what :class:`~autoplay_sdk.chatbot.BaseChatbotWriter` subclasses expect.

Session linking is driven by **outbound Intercom webhooks** to
``POST /chatbot-webhook/{product_id}`` (``conversation.user.created``,
``conversation.user.replied``). The optional reactive browser snippet calls
``POST /sessions/link`` only if you still need client-side linking.

**Proactive assistance (recommended path)** — Evaluate triggers in your app (e.g.
:func:`proactive_trigger_canonical_url_ping_pong`), then send an Intercom admin
reply with ``message_type: quick_reply``. Use :func:`intercom_quick_reply_http_headers`
so ``Intercom-Version`` is **Unstable** (required for tappable buttons — do not
reuse a numeric API version from other Intercom clients).

**Proactive new thread (no existing Messenger conversation)** — Resolve the user
with ``POST {INTERCOM_REST_API_BASE}/contacts/search`` (see
:func:`contacts_search_query_email` / :func:`contacts_search_query_external_id`),
open a user-initiated thread with ``POST .../conversations`` via
:func:`build_create_user_conversation_payload`, then read the id with
:func:`conversation_id_from_create_conversation_response`. Use
:func:`intercom_rest_json_headers` (not Unstable) for those two calls.

**Optional — connector LLM button labels** — ``POST …/intercom/proactive/{product_id}``
(admin key) returns up to three short strings for ``reply_options``. This does not
supply the intro ``body`` text; pair with :func:`build_intercom_quick_reply_reply_payload`.

**Delete conversation (proactive idle teardown)** — use :func:`build_intercom_delete_conversation_request`
in the host's ``delete_remote_chat_thread`` hook (e.g. ``DELETE`` with
:func:`intercom_delete_conversation_url` and :func:`intercom_delete_conversation_headers`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from autoplay_sdk.proactive_triggers.defaults import DEFAULT_PROACTIVE_QUICK_REPLY_BODY

# ---------------------------------------------------------------------------
# Webhook topics (must stay aligned with IntercomChatbot parsing)
# ---------------------------------------------------------------------------

INTERCOM_WEBHOOK_TOPIC_USER_CREATED = "conversation.user.created"
INTERCOM_WEBHOOK_TOPIC_USER_REPLIED = "conversation.user.replied"

INTERCOM_WEBHOOK_TOPICS: tuple[str, ...] = (
    INTERCOM_WEBHOOK_TOPIC_USER_CREATED,
    INTERCOM_WEBHOOK_TOPIC_USER_REPLIED,
)

# ---------------------------------------------------------------------------
# Intercom REST API — quick_reply admin replies
# ---------------------------------------------------------------------------

INTERCOM_REST_API_BASE = "https://api.intercom.io"

INTERCOM_PROACTIVE_PROMPTS_MAX = 3

INTERCOM_HTTP_HEADER_VERSION = "Intercom-Version"

INTERCOM_API_VERSION_QUICK_REPLY = "Unstable"

INTERCOM_API_VERSION_UNSTABLE = INTERCOM_API_VERSION_QUICK_REPLY

# Stable REST (contacts search, create conversation) — align with connector ``INTERCOM_API_VERSION``.
INTERCOM_API_VERSION_REST = "2.11"

# ``DELETE /conversations/{id}`` — Intercom reference uses 2.15+ for delete.
INTERCOM_API_VERSION_DELETE_CONVERSATION = "2.15"

INTERCOM_PROACTIVE_QUICK_REPLY_DEFAULT_BODY = DEFAULT_PROACTIVE_QUICK_REPLY_BODY

# First user-visible line when opening a thread via ``POST /conversations`` (user-initiated).
INTERCOM_CREATE_CONVERSATION_DEFAULT_BODY = (
    "Hi, I'd like some help based on my recent session."
)


def intercom_chatbot_webhook_url(connector_host: str, product_id: str) -> str:
    """Build ``POST /chatbot-webhook/{product_id}`` URL for Intercom outbound webhooks.

    Args:
        connector_host: Connector hostname (``event-connector-xxxx.onrender.com``) or
            full origin (``https://event-connector-xxxx.onrender.com``). A trailing
            slash is stripped.
        product_id: Autoplay product id (path segment, no slashes).

    Returns:
        Absolute HTTPS URL with no trailing slash before ``/chatbot-webhook/``.
    """
    base = _connector_https_base(connector_host)
    if not product_id or "/" in product_id:
        raise ValueError("product_id must be non-empty and must not contain '/'")
    return f"{base}/chatbot-webhook/{product_id}"


def intercom_connector_llm_prompt_labels_url(
    connector_host: str, product_id: str
) -> str:
    """Build ``POST /intercom/proactive/{product_id}`` URL on the event connector.

    This optional endpoint asks the connector to LLM-generate up to
    :data:`INTERCOM_PROACTIVE_PROMPTS_MAX` short strings for quick-reply **button
    labels**. Use :func:`build_connector_llm_prompt_labels_request_body` for the JSON body.

    The primary proactive path is fixed copy + Intercom ``quick_reply`` via
    :func:`build_intercom_quick_reply_reply_payload`; call the connector only when
    you want generated labels instead of static ones.
    """
    base = _connector_https_base(connector_host)
    if not product_id or "/" in product_id:
        raise ValueError("product_id must be non-empty and must not contain '/'")
    return f"{base}/intercom/proactive/{product_id}"


def build_connector_llm_prompt_labels_request_body(
    *,
    session_id: str = "",
    conversation_id: str = "",
    action_count: int = 1,
) -> dict[str, Any]:
    """JSON body for ``POST /intercom/proactive/{product_id}`` (admin key required).

    Fields match the event connector handler.
    """
    return {
        "session_id": session_id.strip(),
        "conversation_id": conversation_id.strip(),
        "action_count": int(action_count),
    }


def normalize_intercom_quick_reply_labels(prompts: Sequence[str]) -> list[str]:
    """Strip empties and cap at :data:`INTERCOM_PROACTIVE_PROMPTS_MAX` labels."""
    out: list[str] = []
    for p in prompts:
        s = str(p).strip()
        if s:
            out.append(s)
        if len(out) >= INTERCOM_PROACTIVE_PROMPTS_MAX:
            break
    return out


def intercom_delete_conversation_url(
    conversation_id: str, *, retain_metrics: bool = True
) -> str:
    """URL for ``DELETE {INTERCOM_REST_API_BASE}/conversations/{id}``."""
    cid = (conversation_id or "").strip()
    q = "true" if retain_metrics else "false"
    return f"{INTERCOM_REST_API_BASE}/conversations/{cid}?retain_metrics={q}"


def intercom_delete_conversation_headers(access_token: str) -> dict[str, str]:
    """Headers for ``DELETE /conversations/{id}`` (Bearer + ``Intercom-Version``)."""
    return intercom_rest_json_headers(
        access_token, api_version=INTERCOM_API_VERSION_DELETE_CONVERSATION
    )


def build_intercom_delete_conversation_request(
    access_token: str,
    conversation_id: str,
    *,
    retain_metrics: bool = True,
) -> tuple[str, dict[str, str]]:
    """Return ``(url, headers)`` for deleting an Intercom conversation."""
    return (
        intercom_delete_conversation_url(
            conversation_id, retain_metrics=retain_metrics
        ),
        intercom_delete_conversation_headers(access_token),
    )


def intercom_rest_json_headers(
    access_token: str, *, api_version: str = INTERCOM_API_VERSION_REST
) -> dict[str, str]:
    """Headers for standard Intercom REST JSON calls (e.g. ``/contacts/search``, ``POST /conversations``).

    Uses :data:`INTERCOM_API_VERSION_REST` by default — not ``Unstable`` (reserved for
    :func:`intercom_quick_reply_http_headers`).
    """
    tok = access_token.strip()
    ver = (api_version or INTERCOM_API_VERSION_REST).strip()
    return {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        INTERCOM_HTTP_HEADER_VERSION: ver,
    }


def contacts_search_query_email(email: str) -> dict[str, Any]:
    """JSON body for ``POST {INTERCOM_REST_API_BASE}/contacts/search`` (match by email)."""
    return {
        "query": {
            "field": "email",
            "operator": "=",
            "value": (email or "").strip(),
        }
    }


def contacts_search_query_external_id(external_id: str) -> dict[str, Any]:
    """JSON body for ``POST {INTERCOM_REST_API_BASE}/contacts/search`` (match by external_id)."""
    return {
        "query": {
            "field": "external_id",
            "operator": "=",
            "value": (external_id or "").strip(),
        }
    }


def first_contact_id_from_search_response(body: Any) -> str | None:
    """Return Intercom contact ``id`` from a ``/contacts/search`` JSON response, or ``None``."""
    if not isinstance(body, dict):
        return None
    data = body.get("data")
    if not isinstance(data, list) or not data:
        return None
    first = data[0]
    if not isinstance(first, dict):
        return None
    cid = first.get("id")
    if cid is None:
        return None
    s = str(cid).strip()
    return s or None


def build_create_user_conversation_payload(
    user_intercom_id: str, body: str | None = None
) -> dict[str, Any]:
    """JSON body for ``POST {INTERCOM_REST_API_BASE}/conversations`` (user-initiated conversation).

    Args:
        user_intercom_id: Intercom contact id (``contacts[].id`` from search).
        body: Opening message text; defaults to :data:`INTERCOM_CREATE_CONVERSATION_DEFAULT_BODY`.
    """
    text = (body or INTERCOM_CREATE_CONVERSATION_DEFAULT_BODY).strip()
    return {
        "from": {"type": "user", "id": (user_intercom_id or "").strip()},
        "body": text,
    }


def conversation_id_from_create_conversation_response(data: Any) -> str | None:
    """Extract ``conversation_id`` from ``POST /conversations`` (or message) JSON."""
    if not isinstance(data, dict):
        return None
    for key in ("conversation_id", "id"):
        raw = data.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    conv = data.get("conversation")
    if isinstance(conv, dict):
        for key in ("id", "conversation_id"):
            raw = conv.get(key)
            if raw is not None and str(raw).strip():
                return str(raw).strip()
    return None


def intercom_quick_reply_http_headers(access_token: str) -> dict[str, str]:
    """Headers for ``POST /conversations/{conversation_id}/reply`` with ``quick_reply``.

    Sets ``Intercom-Version`` to :data:`INTERCOM_API_VERSION_QUICK_REPLY` (``Unstable``).
    """
    tok = access_token.strip()
    return {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
        INTERCOM_HTTP_HEADER_VERSION: INTERCOM_API_VERSION_QUICK_REPLY,
    }


def build_intercom_quick_reply_reply_payload(
    *,
    admin_id: str,
    body: str,
    prompt_labels: Sequence[str],
) -> dict[str, Any]:
    """Build JSON body for Intercom ``POST /conversations/{id}/reply`` (quick_reply).

    ``prompt_labels`` become ``reply_options`` (capped and cleaned via
    :func:`normalize_intercom_quick_reply_labels`). Each option gets a stable
    ``uuid`` slug derived from the label text (same pattern as legacy clients).

    Send with :func:`intercom_quick_reply_http_headers` and base
    :data:`INTERCOM_REST_API_BASE`.
    """
    labels = normalize_intercom_quick_reply_labels(prompt_labels)
    reply_options = []
    for prompt in labels:
        uuid = re.sub(r"[^a-z0-9]+", "_", prompt.lower()).strip("_") or "option"
        reply_options.append({"text": prompt, "uuid": uuid})

    return {
        "message_type": "quick_reply",
        "type": "admin",
        "admin_id": admin_id.strip(),
        "body": body,
        "reply_options": reply_options,
    }


def proactive_trigger_canonical_url_ping_pong(
    urls: Sequence[str | None],
    *,
    min_cycles: int = 1,
) -> bool:
    """True when the user oscillates between canonical URLs (A→B→A pattern).

    Drops empty/None entries, then counts overlapping triples where
    ``seq[i] == seq[i+2]`` and ``seq[i] != seq[i+1]`` (same page, different page,
    back to first). Requires ``min_cycles`` such triples (default 1).

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


def proactive_trigger_canonical_url_ping_pong_projects_either_leg(
    urls: Sequence[str | None],
    *,
    projects_substring: str = "projects",
    min_cycles: int = 1,
) -> bool:
    """A→B→A oscillation where **at least one** of A or B contains ``projects_substring``.

    For each overlapping triple ``(A, B, C)`` with ``A == C`` and ``A != B``, counts a
    cycle only when ``projects_substring`` appears in **A or B** (inclusive OR — neither
    leg is required if the other already qualifies). Empty ``projects_substring`` counts
    every A→B→A triple (same as :func:`proactive_trigger_canonical_url_ping_pong`).
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


@dataclass
class IntercomProactivePolicyConfig:
    """Maps to ``integration_config["proactive"]`` for the optional connector LLM labels endpoint."""

    enabled: bool = True
    min_actions: int = 1
    cooldown_seconds: float = 0.0

    def to_integration_config_fragment(self) -> dict[str, dict[str, Any]]:
        """Return ``{\"proactive\": {...}}`` for merging into product registration."""
        return {
            "proactive": {
                "enabled": self.enabled,
                "min_actions": self.min_actions,
                "cooldown_seconds": self.cooldown_seconds,
            }
        }


def _connector_https_base(connector_host: str) -> str:
    """Normalize connector host to ``https://host`` origin (no path)."""
    host = connector_host.strip().rstrip("/")
    if not host:
        raise ValueError("connector_host must be non-empty")
    if host.startswith("http://") or host.startswith("https://"):
        base = host
    else:
        base = f"https://{host}"
    return base.rstrip("/")


# ---------------------------------------------------------------------------
# Optional: browser-assisted snippet (``POST /sessions/link``)
# ---------------------------------------------------------------------------

_REACTIVE_FETCH_PATH = "/sessions/link"

REACTIVE_SESSION_LINK_SCRIPT_TEMPLATE = """\
<script>
window.Intercom("onConversationStarted", function (data) {{
  var sessionId = typeof posthog !== "undefined" ? posthog.get_session_id() : null;
  if (!sessionId || !data.conversation_id) return;
  fetch("https://{connector_hostname}" + "{fetch_path}", {{
    method: "POST",
    headers: {{ "Content-Type": "application/json" }},
    body: JSON.stringify({{
      product_id: "{product_id}",
      session_id: sessionId,
      conversation_id: data.conversation_id,
    }}),
  }}).catch(function (e) {{
    console.warn("[autoplay] session link failed:", e);
  }});
}});
</script>"""


def _normalize_hostname_for_fetch(connector_host: str) -> str:
    """Return host[:port] without scheme or path for ``https://`` + host fetches."""
    h = connector_host.strip().rstrip("/")
    if h.startswith("https://"):
        h = h[8:]
    elif h.startswith("http://"):
        h = h[7:]
    h = h.split("/")[0]
    return h


def format_reactive_session_link_script(
    connector_host: str,
    product_id: str,
) -> str:
    """Return HTML/JS snippet for ``onConversationStarted`` → ``POST /sessions/link``.

    Prefer configuring Intercom webhooks to ``/chatbot-webhook/{product_id}``;
    use this only when you still need the browser to pass ``conversation_id``.
    """
    hostname = _normalize_hostname_for_fetch(connector_host)
    return REACTIVE_SESSION_LINK_SCRIPT_TEMPLATE.format(
        connector_hostname=hostname,
        product_id=product_id.replace('"', '\\"'),
        fetch_path=_REACTIVE_FETCH_PATH,
    )
