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
from autoplay_sdk.chatbot import BaseChatbotWriter
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
from autoplay_sdk.agent_context import AsyncAgentContextWriter
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
