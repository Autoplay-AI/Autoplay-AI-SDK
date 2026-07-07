---
name: chatbot-template
description: >-
  [One sentence: what this skill does and when to use it.]
  Use when the customer picks [PLATFORM] during autoplay-chatbot setup, or
  asks how to connect their [PLATFORM] account to Autoplay.
disable-model-invocation: true
---

# Chatbot — [PLATFORM NAME]

> Read `autoplay-core` first — the `CONNECTOR_URL` and `PRODUCT_ID` from
> that step are required here.

## How it works (customer never deploys a server)

```
User does actions in the product
        ↓
PostHog captures them → Autoplay connector buffers
        ↓
User opens [PLATFORM] chat → sends a message → conversation created
        ↓
[PLATFORM] webhook fires → POST {CONNECTOR_URL}/chatbot-webhook/{PRODUCT_ID}
        ↓
Autoplay connector:
  • posts buffered activity as internal note (agent context)
  • [optional: generates Claude reply → delivers to user]
        ↓
Agent sees exactly what the user was doing before they asked for help.
```

The customer only configures their [PLATFORM] account. The Autoplay connector
handles everything else and is already running.

---

## Credentials to collect

Ask the customer for these values. Store in `.env`.

```
[CREDENTIAL_1]   — [what it is, where to find it in the platform UI]
[CREDENTIAL_2]   — [what it is, where to find it in the platform UI]
```

**Note on auth format:** [Describe how the platform authenticates API calls —
Bearer token, Basic auth, API key header, etc. Call out any non-obvious format
requirements, e.g. Zendesk's `/token` suffix in Basic auth.]

---

## Preflight — verify credentials before touching anything

Run this and bail on failure. Do not proceed until this passes.

```python
import httpx

# TODO: replace with platform-specific credential variables
credential = "[CREDENTIAL_VALUE]"
headers    = {"Authorization": "[AUTH_SCHEME] [credential]"}  # e.g. f"Bearer {token}"
base       = "[PLATFORM_API_BASE]"  # e.g. "https://api.example.com/v2"

async with httpx.AsyncClient(base_url=base) as client:
    r = await client.get("/[whoami_endpoint]", headers=headers)
    assert r.status_code == 200, f"Auth failed ({r.status_code}): {r.text}"
    me = r.json()["[user_field]"]
    print(f"✓ Authenticated as {me}")
```

**If this fails:** [Most common auth mistake for this platform and exact fix.]

---

## Step 1 — Register webhook in [PLATFORM]

[Describe the webhook registration process. Answer:
- Single API call or multi-step?
- Which event topics to subscribe to?
- Does the platform require a verification/handshake step?
- Where in the platform UI can the customer confirm it worked?]

The webhook endpoint must point at the Autoplay connector (already running —
no server for the customer to deploy):

```python
import os
import httpx

product_id    = os.environ["AUTOPLAY_PRODUCT_ID"]
connector_url = os.environ["CONNECTOR_URL"]  # from autoplay-core setup
endpoint      = f"{connector_url.rstrip('/')}/chatbot-webhook/{product_id}"

# TODO: replace with platform-specific webhook registration call
# Confirm with the customer before sending:
print(f"About to register webhook in [PLATFORM]: {endpoint}")
confirm = input("Confirm? [y/n] ")
if confirm.lower() != "y":
    raise SystemExit("Aborted")

async with httpx.AsyncClient(base_url=base) as client:
    r = await client.post(
        "/[webhooks_endpoint]",
        headers=headers,
        json={
            # TODO: platform-specific payload
            "url": endpoint,
            "events": ["[EVENT_TYPE_1]", "[EVENT_TYPE_2]"],
        },
    )
    r.raise_for_status()
    print(f"✓ Webhook registered: {r.json()}")
```

Confirm in [PLATFORM] UI: [where to verify the webhook is active]

---

## Step 2 — Smoke test

Ask the customer to:
1. Open their product in a browser with PostHog running and `posthog.identify()` called
2. Perform 2–3 actions (page views, clicks, form submits)
3. Open [PLATFORM] chat and send a message

Then verify the internal note appeared on the conversation:

```bash
# TODO: replace with platform-specific API call to list conversation notes
curl -H "Authorization: [AUTH_SCHEME] $[CREDENTIAL_VAR]" \
  "[PLATFORM_API_BASE]/[conversations_endpoint]/{CONVERSATION_ID}/[notes_endpoint]"
```

Expected — an internal note containing the user's recent actions:

```
session_id: $posthog_session_id
timestamp: 2026-06-04 14:30:00 UTC

[1] Visited /dashboard — User landed on the Dashboard
[2] Clicked Export — User clicked the Export button
```

If this appears within 10 seconds, the integration is complete. ✓

---

## Failure modes and exact fixes

**1 — Authentication fails**
[Most common auth mistake for this platform and exact fix.]
[Where in the platform UI to check permissions.]

**2 — Webhook registered but never fires**
[Why webhooks might silently not fire on this platform.]
[How to confirm webhook activity — activity log, test button, etc.]

**3 — Webhook fires but conversation_id is missing**
The webhook payload field names don't match what the connector expects.
Log the raw payload and check `ticket_id` / `conversation_id` field names.

**4 — Internal note not appearing**
[Platform-specific: permission level, note visibility, internal vs public flag.]
Also check: was the pre-link buffer empty? The user must do actions before
opening the chat, not after.

**5 — No session for user identity**
The identity in the [PLATFORM] webhook (email or user_id) doesn't match
what was passed to `posthog.identify()` on the frontend.
Both must be identical strings — check for spaces, case differences.

---

## Reference

- [PLATFORM] API docs: [URL]
- [PLATFORM] webhook docs: [URL]
- Autoplay core skill: `autoplay-core`

---

## Implementation notes (for Autoplay team — not shown to customer)

When adding this integration to the connector server-side:

- **Writer class:** `[PLATFORM]Writer(BaseChatbotWriter)` — implement `_post_note`
  and `_redact_part`. `_post_note` must return a truthy value on success (returning
  `None` causes `BaseChatbotWriter` to unlink the session and log a false failure).
- **Webhook topics:** Set `SESSION_LINK_WEBHOOK_TOPICS` to the event strings that
  fire when a conversation is created or the user replies.
- **Payload parsing:** Override `_parse_session_link_webhook_payload` to extract
  `conversation_id` and `email`/`external_id` from the platform's webhook body.
- **Registration:** The `register_[platform].py` script (run by the agent in Step 1)
  should use the platform's API to register the webhook and confirm it's active.
- **Loop prevention:** If the platform fires webhooks on agent replies too, add a
  cooldown guard: skip if this ticket/conversation was replied to within 5 seconds.