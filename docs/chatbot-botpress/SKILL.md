---
title: "Chatbot Botpress"
sidebarTitle: "Chatbot Botpress"
description: "Wires the Autoplay SDK into Botpress by pulling a user's live activity on demand from the Autoplay connector inside a FetchEventsData code node and injecting it into an Autonomous Agent via agentContext. Covers the two-node Start -> FetchEventsData -> Autonomous Agent -> End workflow and the system prompt pattern. Use when the user mentions Botpress, Botpress Studio, Autonomous Agent, or asks how to give their Botpress bot real-time context."
---

# Chatbot — Botpress

> Read `autoplay-core` first for install and credentials (`product_id`, `mcp_url`, `mcp_key`).

## Scoping pattern for Botpress

The live-activity read is keyed by `product_id` + `user_id` — there is no session concept and no local table to keep in sync. `FetchEventsData` calls the connector directly, synchronously, every time a user sends a message.

**`user_id` must exactly equal** the id your activity source identifies the user with (the value passed to `posthog.identify(...)` / `amplitude.setUserId(...)`).

---

## Architecture: one path, no background process

```
Start -> FetchEventsData -> Autonomous Agent -> End
```

`FetchEventsData` pulls the user's recent actions directly from the connector on every message. There is no webhook node, no `AutoPlayEventsTable`, no `AutoPlayEventsSummaryTable`, and no separate listener process to run — the events already live in Autoplay's connector; Botpress just asks for them when it needs them.

---

## Step 1 — Create the workflow

In Botpress Studio, create a workflow with two nodes: `FetchEventsData` (Code) and `Autonomous Agent` (AI Agent). Connect `Start -> FetchEventsData -> Autonomous Agent -> End`.

## Step 2 — FetchEventsData code node

```javascript
// FetchEventsData code node
const PRODUCT_ID = "YOUR_PRODUCT_ID"
const MCP_KEY = "YOUR_MCP_KEY"  // from onboard_product — store as a bot/workflow secret if your plan supports it

const userId = event.state?.user?.userId ?? event.userId  // must equal the id your activity source identifies the user with

let recentEvents = []
try {
  const res = await fetch(
    `https://mcp.autoplay.ai/users/${PRODUCT_ID}/${userId}/live-activity?limit=10`,
    { headers: { Authorization: `Bearer ${MCP_KEY}` } },
  )
  if (!res.ok) throw new Error(`live-activity ${res.status}`)
  const data = await res.json()
  recentEvents = data.actions
} catch (e) {
  // Fail open — the Autonomous Agent still answers, just without extra context
  console.warn('Autoplay live-activity unavailable', e)
}

workflow.agentContext = { recentEvents, summary: null }
```

`data.actions` comes back already ordered oldest -> newest. `summary` is `null` on purpose — there's no rolling LLM summary anymore, the connector already returns a bounded recent window and the raw actions are passed straight through.

## Step 3 — Autonomous Agent system prompt

Create a workflow variable `agentContext` (Scope: Workflow, Type: Object), then reference it in the Agent instructions:

```
You are a helpful assistant for {{botName}}.

## Real-time user context
{{workflow.agentContext}}

Use the context above to give specific, page-aware answers.
If context is empty, answer normally without mentioning it.
```

---

## Reference

- Full tutorial: https://developers.autoplay.ai/recipes/botpress
- Botpress code nodes / fetch: https://botpress.com/docs
