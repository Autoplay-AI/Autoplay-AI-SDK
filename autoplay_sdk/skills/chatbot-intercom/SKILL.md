---
name: chatbot-intercom
description: >-
  Wires the Autoplay SDK into Intercom by posting real-time user activity as internal
  admin notes. Covers BaseChatbotWriter subclass, conv_map session linking,
  on_session_linked flush, webhook registration, and note redaction for summary
  replacement. Use when the user mentions Intercom, internal notes, conversation_id
  linking, BaseChatbotWriter, or asks how to give their Intercom bot real-time context.
disable-model-invocation: true
---

# Chatbot — Intercom

> Read `autoplay-core` first for install, credentials, and the stream wiring pattern.

## Scoping pattern for Intercom

Intercom has a persistent `conversation_id`. You **must** link it to the Autoplay `session_id` before context can be delivered.

```python
conv_map: dict[str, str] = {}  # session_id → conversation_id
```

- Populate `conv_map` from your Intercom webhook handler (Step 1)
- Call `await writer.on_session_linked(session_id, conversation_id)` immediately after each link
- `write_actions_cb` guards on `conv_map.get(session_id)` — actions before the link are buffered, not dropped
- The first link is **sticky** — never re-link the same session

---

## Step 1 — Register Intercom webhooks

In Intercom: **Settings → Integrations → Developer Hub → Your app → Webhooks**

Subscribe to:
- `conversation.user.created`
- `conversation.user.replied`

```python
from autoplay_sdk.integrations.intercom import INTERCOM_WEBHOOK_TOPICS
print(INTERCOM_WEBHOOK_TOPICS)  # copy these into Intercom Developer Hub
```

In your webhook handler: verify `X-Hub-Signature-256` with your `client_secret`, extract `conversation_id`, resolve `session_id` from the user identity, then populate `conv_map` and call `on_session_linked`.

---

## Step 2 — Implement IntercomWriter

```python
import httpx
from autoplay_sdk.chat.chatbot import BaseChatbotWriter
from autoplay_sdk.integrations.intercom import INTERCOM_WEBHOOK_TOPICS

ACCESS_TOKEN = "your-intercom-access-token"
ADMIN_ID = "your-admin-id"

http = httpx.AsyncClient(
    base_url="https://api.intercom.io",
    headers={
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Accept": "application/json",
        "Intercom-Version": "2.11",
    },
)

class IntercomWriter(BaseChatbotWriter):
    SESSION_LINK_WEBHOOK_TOPICS = INTERCOM_WEBHOOK_TOPICS

    async def _post_note(self, conversation_id: str, body: str) -> str | None:
        r = await http.post(
            f"/conversations/{conversation_id}/parts",
            json={"type": "admin", "admin_id": ADMIN_ID,
                  "message_type": "note", "body": body},
        )
        if r.is_success:
            parts = r.json().get("conversation_parts", {}).get("conversation_parts", [])
            return str(parts[-1]["id"]) if parts else None
        return None

    async def _redact_part(self, conversation_id: str, part_id: str) -> None:
        await http.post("/conversations/redact", json={
            "type": "conversation_part",
            "conversation_id": conversation_id,
            "conversation_part_id": part_id,
        })
```

**Intercom credentials:**
- Access token: Developer Hub → Your app → Authentication
- Admin ID: [Admins API](https://developers.intercom.com/docs/references/rest-api/api.intercom.io/Admins/listAdmins/)

---

## Step 3 — Wire AsyncAgentContextWriter

```python
from collections import defaultdict
from autoplay_sdk.context.agent_context import AsyncAgentContextWriter
from autoplay_sdk import AsyncSessionSummarizer

conv_map: dict[str, str] = {}
part_ids: dict[str, list[str]] = defaultdict(list)
writer = IntercomWriter(product_id="your-product-id")

async def write_actions_cb(session_id: str, text: str) -> None:
    conv_id = conv_map.get(session_id)
    if not conv_id:
        return
    part_id = await writer._post_note(conv_id, text)
    if part_id:
        part_ids[session_id].append(part_id)

async def overwrite_cb(session_id: str, summary: str) -> None:
    conv_id = conv_map.get(session_id)
    if not conv_id:
        return
    await writer._post_note(conv_id, summary)          # post summary first
    old = part_ids.pop(session_id, [])
    if old:
        import asyncio
        await asyncio.gather(*[writer._redact_part(conv_id, pid) for pid in old])

agent_writer = AsyncAgentContextWriter(
    summarizer=AsyncSessionSummarizer(llm=llm, threshold=20),
    write_actions=write_actions_cb,
    overwrite_with_summary=overwrite_cb,
    debounce_ms=0,
)
```

After each webhook link: `await writer.on_session_linked(session_id, conversation_id)`

---

## Reference

- Full tutorial: https://developers.autoplay.ai/recipes/intercom-tutorial
- Chatbot writer SDK docs: https://developers.autoplay.ai/sdk/chatbot-writer
- Agent context SDK docs: https://developers.autoplay.ai/sdk/agent-context

---

## Known Pitfalls

### Gap 1 — Circular import from `autoplay_sdk.integrations.intercom`

**The cycle that existed:**

```
integrations.__init__
  → intercom.py
    → autoplay_sdk.proactive.triggers.defaults
      → builtin_catalog
        → canonical_ping_pong.py
          → integrations.intercom   ← cycle closes here
```

**SDK fix (already applied):** `proactive_trigger_canonical_url_ping_pong` and
`proactive_trigger_canonical_url_ping_pong_projects_either_leg` were moved to
`autoplay_sdk.proactive.triggers._url_predicates`. `intercom.py` re-imports and
re-exports both functions so all existing callers are unaffected.

**If you write custom triggers:** never import both
`autoplay_sdk.integrations.intercom` and any `autoplay_sdk.proactive` module at
the module top level in the same file. Use a deferred (inside-function) import
as a fallback if you must cross the boundary.

---

### Gap 2 — Proactive popup only fires on widget-initiated conversations

`POST /conversations` with `from: {type: "user"}` creates a conversation visible
in the **admin inbox only** — it does **not** trigger a notification popup in the
Messenger widget for the end user.

The popup fires only when the admin replies to a conversation the user
**genuinely initiated through the widget** (captured via the
`conversation.user.created` webhook and stored in Redis as
`intercom_conv:{session_id}`).

**Correct proactive sequence:**

1. User opens the Messenger widget and sends any message → Intercom fires
   `conversation.user.created` webhook.
2. Webhook handler stores `conv_id` in Redis keyed to `session_id`:
   ```python
   await redis.set(f"intercom_conv:{session_id}", conv_id, ex=3600)
   ```
3. `trigger_notification.py` reads the real `conv_id` from Redis and POSTs the
   `quick_reply` admin reply into it:
   ```python
   conv_id = await redis.get(f"intercom_conv:{session_id}")
   if not conv_id:
       return  # user never opened widget — popup is impossible
   await http.post(
       f"/conversations/{conv_id}/reply",
       headers=intercom_quick_reply_http_headers(ACCESS_TOKEN),
       json=build_intercom_quick_reply_reply_payload(
           admin_id=ADMIN_ID,
           body="Can I help you with something?",
           quick_reply_options=["Yes, show me", "No thanks"],
       ),
   )
   ```
4. Intercom surfaces the admin reply as a popup notification in the widget.

---

### Gap 3 — Proactive config JSON schema and routing pattern

The `integration_config["proactive_intercom"]` field is a **list** of trigger
config objects (v2 format). Each entry has a `messages` array of chip rows.

```json
{
  "proactive_intercom": [
    {
      "proactive_criteria": {"id": "canonical_ping_pong"},
      "messages": [
        {
          "id": "stuck_on_projects",
          "label": "Help me navigate projects",
          "user_tour_exists": true,
          "user_tour_id": "tour-abc123"
        },
        {
          "id": "general_help",
          "label": "Show me around",
          "user_tour_exists": false
        }
      ]
    }
  ]
}
```

Field name back-compat: both `user_tour_exists`/`user_tour_id` (v2) and
`offers_tour`/`flow_id` (v1) are accepted by the parser.

**SDK helpers from `proactive_intercom_config.py`:**

```python
from autoplay_sdk.proactive.triggers.proactive_intercom_config import (
    quick_reply_labels_from_messages_config,
    resolve_tour_offer_for_inbound,
)

# Build the chip label list for the quick_reply payload
labels = quick_reply_labels_from_messages_config(integration_config)
# → ("Help me navigate projects", "Show me around")

# After the user taps a chip, check whether it maps to a tour
tour_id = resolve_tour_offer_for_inbound(
    integration_config,
    user_message=tapped_chip_text,
    default_flow_id="tour-fallback",
)
if tour_id:
    # Send Yes/No tour offer; on "Yes" launch the UserTour flow
    ...
else:
    # Route to RAG / LLM fallback
    ...
```

---

### Gap 4 — API version header table

Use the **correct header builder** per operation. Reusing `2.11` for `quick_reply`
silently breaks tappable buttons.

| Operation | Helper | `Intercom-Version` |
|---|---|---|
| `POST /contacts/search` | `intercom_rest_json_headers()` | `2.11` |
| `POST /conversations` | `intercom_rest_json_headers()` | `2.11` |
| `POST /conversations/{id}/reply` (quick_reply) | `intercom_quick_reply_http_headers()` | `Unstable` |
| `DELETE /conversations/{id}` | `intercom_delete_conversation_headers()` | `2.15` |

```python
from autoplay_sdk.integrations.intercom import (
    intercom_rest_json_headers,
    intercom_quick_reply_http_headers,
    intercom_delete_conversation_headers,
)
```

---

### Gap 5 — Redis URL differs between Docker and local dev

`REDIS_URL=redis://redis:6379` uses the Docker Compose service name and will fail
when running the connector outside Docker (e.g. local `uvicorn` or tests).

Recommended fix — add this normalization wherever you initialise the Redis client:

```python
import os

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379").replace(
    "redis://redis:", "redis://localhost:"
)
```

This is a no-op in Docker (the hostname stays `redis:6379`) and transparently
rewrites the URL to `localhost` everywhere else.
