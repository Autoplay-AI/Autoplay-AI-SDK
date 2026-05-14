---
name: chatbot-botpress
description: >-
  Wires the Autoplay SDK into Botpress by storing real-time user activity in Botpress
  Tables and injecting it into an Autonomous Agent via agentContext. Covers the dual
  Webhook + chat flow path, AutoPlayEventsTable, AutoPlayEventsSummaryTable, and the
  system prompt pattern. Use when the user mentions Botpress, Botpress Studio,
  Botpress Tables, Autonomous Agent, or asks how to give their Botpress bot real-time context.
disable-model-invocation: true
---

# Chatbot — Botpress

> Read `autoplay-core` first for install, credentials, and the stream wiring pattern.

## Scoping pattern for Botpress

`session_id` is the table key. No `conv_map` needed — Botpress Tables are keyed directly by `session_id`. The Autonomous Agent reads the table on every message.

**Never mix rows from different `session_id` values** — always filter table queries by `session_id`.

---

## Architecture: two parallel paths

```
WebHook → StoreEventsData      (writes every ActionsPayload to AutoPlayEventsTable)
Start → FetchEventsData → Autonomous Agent → End   (reads table on each user message)
```

---

## Step 1 — Create Botpress Tables

In Botpress Studio create two tables:

**`AutoPlayEventsTable`**
| Column | Type |
|--------|------|
| `title` | String |
| `description` | String |
| `canonical_url` | String |
| `user_id` | String |
| `product_id` | String |
| `session_id` | String |

**`AutoPlayEventsSummaryTable`**
| Column | Type |
|--------|------|
| `summary` | String |
| `session_id` | String |

---

## Step 2 — StoreEventsData code node

Webhook fires on every `ActionsPayload`. Write each action as a row:

```javascript
// StoreEventsData code node
const payload = event.payload;
const sessionId = payload.session_id;

for (const action of payload.actions) {
  await client.createTableRow({
    table: "AutoPlayEventsTable",
    row: {
      title: action.title,
      description: action.description,
      canonical_url: action.canonical_url ?? "",
      user_id: payload.user_id ?? "",
      product_id: payload.product_id,
      session_id: sessionId,
    },
  });
}
```

---

## Step 3 — FetchEventsData code node

Runs before the Autonomous Agent on every user message. Fetches recent rows for this session:

```javascript
// FetchEventsData code node
const sessionId = event.userId;  // or however you surface session_id in Botpress

const rows = await client.findTableRows({
  table: "AutoPlayEventsTable",
  filter: { session_id: sessionId },
  limit: 20,
  orderBy: [{ column: "id", direction: "desc" }],
});

const summaryRows = await client.findTableRows({
  table: "AutoPlayEventsSummaryTable",
  filter: { session_id: sessionId },
  limit: 1,
});

workflow.agentContext = [
  summaryRows[0]?.summary ? `Session summary: ${summaryRows[0].summary}` : "",
  rows.rows.map(r => `- ${r.title}: ${r.description} (${r.canonical_url})`).join("\n"),
].filter(Boolean).join("\n\n");
```

---

## Step 4 — Autonomous Agent system prompt

Add `{{workflow.agentContext}}` to the agent's system prompt:

```
You are a helpful assistant for {{botName}}.

## Real-time user context
{{workflow.agentContext}}

Use the context above to give specific, page-aware answers.
If context is empty, answer normally without mentioning it.
```

---

## Step 5 — Python stream worker (posts to Botpress webhook)

```python
import httpx
from autoplay_sdk import AsyncConnectorClient, AsyncSessionSummarizer
from autoplay_sdk.agent_context import AsyncAgentContextWriter

BOTPRESS_WEBHOOK_URL = "https://webhook.botpress.cloud/YOUR_WEBHOOK_ID"

async def write_actions_cb(session_id: str, text: str) -> None:
    async with httpx.AsyncClient() as http:
        await http.post(BOTPRESS_WEBHOOK_URL, json={
            "type": "actions", "session_id": session_id, "text": text
        })

async def overwrite_cb(session_id: str, summary: str) -> None:
    async with httpx.AsyncClient() as http:
        await http.post(BOTPRESS_WEBHOOK_URL, json={
            "type": "summary", "session_id": session_id, "summary": summary
        })

agent_writer = AsyncAgentContextWriter(
    summarizer=AsyncSessionSummarizer(llm=llm, threshold=20),
    write_actions=write_actions_cb,
    overwrite_with_summary=overwrite_cb,
    debounce_ms=0,
)
```

---

## Reference

- Full tutorial: https://developers.autoplay.ai/recipes/botpress
- Botpress Tables API: https://botpress.com/docs/api-reference/tables
