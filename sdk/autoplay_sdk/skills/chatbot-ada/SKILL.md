---
name: chatbot-ada
description: >-
  Wires the Autoplay SDK into Ada (ada.cx) by injecting real-time user context via
  Ada metaFields on web apps. Covers Ada Variables setup, FastAPI context endpoint,
  and the adaEmbed web SDK integration. Use when the user mentions Ada, ada.cx,
  adaEmbed, metaFields, or asks how to give their Ada bot real-time context.
disable-model-invocation: true
---

# Chatbot — Ada (ada.cx)

> Read `autoplay-core` first for install, credentials, and the stream wiring pattern.

## Scoping pattern for Ada

Ada does not have a persistent server-side `conversation_id` before the chat opens. **No `conv_map` needed.** Instead:

- Store context in a dict keyed by `session_id`
- Expose a FastAPI endpoint: `GET /context/{session_id}`
- Frontend fetches context **before** calling `adaEmbed.start()`
- Pass the result as `metaFields`

`session_id` = `window.posthog.get_distinct_id()` (Web) or your PostHog distinct ID (mobile).

---

## Step 1 — Define Ada Variables

In Ada dashboard → **Build → Variables → + New Variable**:

| Variable name | Type   |
|---------------|--------|
| `session_id`  | String |
| `current_page`| String |
| `recent_actions` | String |
| `session_summary` | String |

Key rules: no spaces, emojis, or periods. Keys are case-sensitive.

---

## Step 2 — Context store + stream callbacks

```python
# ada_context.py
from dataclasses import dataclass

context_store: dict[str, "AdaContext"] = {}

@dataclass
class AdaContext:
    session_id: str
    current_page: str = ""
    recent_actions: str = ""
    session_summary: str = ""

def get_context(session_id: str) -> AdaContext:
    return context_store.get(session_id, AdaContext(session_id=session_id))

async def write_actions_cb(session_id: str, text: str) -> None:
    ctx = context_store.setdefault(session_id, AdaContext(session_id=session_id))
    ctx.recent_actions = text
    for line in reversed(text.splitlines()):
        if "navigated to" in line.lower() or "visited" in line.lower():
            ctx.current_page = line.strip()
            break

async def overwrite_cb(session_id: str, summary: str) -> None:
    ctx = context_store.setdefault(session_id, AdaContext(session_id=session_id))
    ctx.session_summary = summary
    ctx.recent_actions = ""
```

---

## Step 3 — FastAPI context endpoint

```python
from fastapi import FastAPI
from ada_context import get_context

app = FastAPI()

@app.get("/context/{session_id}")
async def context_for_session(session_id: str):
    ctx = get_context(session_id)
    return {
        "session_id": ctx.session_id,
        "current_page": ctx.current_page,
        "recent_actions": ctx.recent_actions,
        "session_summary": ctx.session_summary,
    }
```

Protect this endpoint in production — validate with a session cookie or signed token.

---

## Step 4 — Inject metaFields (Web)

```javascript
const SESSION_ID = window.posthog?.get_distinct_id() ?? "anonymous";

async function openAdaWithContext() {
  let meta = { session_id: SESSION_ID, current_page: window.location.pathname,
               recent_actions: "", session_summary: "" };
  try {
    const ctx = await fetch(`/context/${SESSION_ID}`).then(r => r.json());
    meta = { ...meta, ...ctx };
  } catch (e) { console.warn("Autoplay context unavailable", e); }

  if (window.adaEmbed) {
    await window.adaEmbed.setMetaFields(meta);
    await window.adaEmbed.toggle();
    return;
  }
  await window.adaEmbed.start({
    handle: "YOUR-BOT-HANDLE",
    metaFields: meta,
    adaReadyCallback: () => window.adaEmbed.toggle(),
  });
}

// SPA: update current_page on navigation
window.addEventListener("popstate", async () => {
  if (window.adaEmbed)
    await window.adaEmbed.setMetaFields({ current_page: window.location.pathname });
});
```

Ada embed script (add to `<head>`, use `data-lazy`):
```html
<script id="__ada" data-handle="YOUR-BOT-HANDLE" data-lazy
  src="https://static.ada.support/embed2.js"></script>
```

---

---

## Reference

- Full tutorial: https://developers.autoplay.ai/recipes/ada
- Ada Web SDK: https://docs.ada.cx/chat/web/sdk-api-reference
