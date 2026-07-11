---
title: "Ada skill"
sidebarTitle: "Ada"
description: "Connects an existing Ada bot to Autoplay live activity by pulling a user's recent activity on demand and injecting it through Ada metaFields. Covers Ada variables, a small context endpoint, and matching Ada's user identifier to the activity source. Use when the customer already uses Ada, ada.cx, adaEmbed, metaFields, or asks how to give Ada real-time Autoplay context."
---

# AI Support Agent — Ada (ada.cx)

> Read `autoplay-core` first for install and credentials (`product_id`, `mcp_url`, `mcp_key`).

## Scoping pattern for Ada

Ada does not have a persistent server-side `conversation_id` before the chat opens, and the live-activity read has no session concept — it's keyed by `product_id` + `user_id` only.

- Expose a FastAPI endpoint: `GET /context/{user_id}`
- It calls the Autoplay connector synchronously and returns the result — no local store, no background process
- Frontend fetches context **before** calling `adaEmbed.start()`
- Pass the result as `metaFields`

`user_id` must be the same stable id your activity source identifies the user with — `posthog.identify(user.id)` / `amplitude.setUserId(user.id)` — not a session id, not email.

---

## Step 1 — Define Ada Variables

In Ada dashboard → **Build → Variables → + New Variable**:

| Variable name | Type   |
|---------------|--------|
| `user_id`     | String |
| `current_page`| String |
| `recent_actions` | String |

Key rules: no spaces, emojis, or periods. Keys are case-sensitive. (No `session_summary` variable — the connector already returns a bounded recent window, so there's no separate summary to store.)

---

## Step 2 — FastAPI context endpoint

```python
# api.py
import httpx
from fastapi import FastAPI

app = FastAPI()

CONNECTOR_URL = "https://mcp.autoplay.ai"   # origin of mcp_url, without /mcp
PRODUCT_ID = "YOUR_PRODUCT_ID"              # from onboard_product
MCP_KEY = "YOUR_MCP_KEY"                    # from onboard_product

@app.get("/context/{user_id}")
async def context_for_user(user_id: str):
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{CONNECTOR_URL}/users/{PRODUCT_ID}/{user_id}/live-activity",
            params={"limit": 10},
            headers={"Authorization": f"Bearer {MCP_KEY}"},
        )
    if res.status_code != 200:
        # Omit current_page so the frontend's `{ ...meta, ...ctx }` spread
        # doesn't clobber the real window.location.pathname it already set.
        return {"user_id": user_id, "recent_actions": ""}

    actions = res.json().get("actions", [])
    current_page = actions[-1]["canonical_url"] if actions else ""
    recent_actions = "\n".join(
        f"[{i + 1}] {a['title']} — {a['description']}" for i, a in enumerate(actions)
    )
    return {"user_id": user_id, "current_page": current_page, "recent_actions": recent_actions}
```

Protect this endpoint in production — validate with a session cookie or signed token, not the raw `user_id` alone.

---

## Step 3 — Inject metaFields (Web)

```javascript
const USER_ID = window.currentUser?.id ?? null;  // same id passed to posthog.identify(...)

async function openAdaWithContext() {
  let meta = { user_id: USER_ID ?? "anonymous", current_page: window.location.pathname, recent_actions: "" };
  if (USER_ID) {
    try {
      const ctx = await fetch(`/context/${USER_ID}`).then(r => r.json());
      meta = { ...meta, ...ctx };
    } catch (e) { console.warn("Autoplay context unavailable", e); }
  }

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

## Reference

- Full tutorial: https://developers.autoplay.ai/recipes/ada
- Ada Web SDK: https://docs.ada.cx/chat/web/sdk-api-reference
