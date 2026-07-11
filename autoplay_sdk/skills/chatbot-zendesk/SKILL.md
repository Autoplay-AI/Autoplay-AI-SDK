---
skill: chatbot-zendesk
family: chatbot
version: 0.1.0
sdk_min: 0.7.1
tags: [zendesk, notes, webhooks]
name: chatbot-zendesk
description: >-
  Connects an existing Zendesk workspace to Autoplay so real-time user activity can be
  injected into tickets as internal notes and the Autoplay connector can post
  context-aware replies. Covers customer-provided Zendesk credentials, webhook and
  trigger registration, and the legacy push path where Zendesk does not use MCP
  directly. Use when the customer already uses Zendesk and wants Autoplay context in
  tickets.
disable-model-invocation: true
---

# AI Support Agent — Zendesk

> Read `autoplay-core` first for install, product registration, and the
> PostHog → connector smoke test. The `CONNECTOR_URL` and `PRODUCT_ID` from
> that step are required here.

## How it works (customer never deploys a server)

Two separate connector endpoints handle the two Zendesk events:

```
User does actions in the product
        ↓
PostHog captures them → Autoplay connector buffers (ZendeskChatbot worker)
        ↓
User opens Zendesk widget → sends a message → ticket created
        ↓
Zendesk Trigger A (new_ticket)
  → POST {CONNECTOR_URL}/chatbot-webhook/{PRODUCT_ID}
  → Connector links the session → posts buffered activity as internal note
        ↓
User sends another message → Zendesk Trigger B (user_reply)
  → POST {CONNECTOR_URL}/zendesk/chat/{PRODUCT_ID}
  → Connector builds RAG context (PostHog events + session)
  → Calls Claude LLM → posts public reply on the ticket
        ↓
User sees context-aware Claude reply.
Agent sees internal note with what the user was doing before contacting support.
```

The customer only configures their Zendesk account. Everything else is handled
by the Autoplay connector that is already running.

**Why two endpoints?**
- `/chatbot-webhook/{PRODUCT_ID}` — generic chatbot session-link route. Handles
  `new_ticket`: looks up the PostHog session by email, links it to the ticket,
  flushes buffered actions as an internal note.
- `/zendesk/chat/{PRODUCT_ID}` — Zendesk-specific LLM reply route. Handles
  `user_reply`: reads the user message from the trigger payload, assembles RAG
  context (buffered events + session history), calls Claude, posts a public reply.

---

## Credentials to collect

Ask the customer for these three values. Store in `.env`.

```
ZENDESK_SUBDOMAIN   — the part before .zendesk.com in their URL
                      e.g. "mycompany" from mycompany.zendesk.com

ZENDESK_EMAIL       — the admin email they use to log into Zendesk
                      must be an active admin or agent on the account

ZENDESK_API_TOKEN   — Admin Center → Apps and integrations → APIs
                      → API configuration → Allow API token access (must be ON)
                      → API tokens → Add API token
```

Register the product with `integration_type=zendesk` in the connector's
`PRODUCTS_CONFIG`:

```json
{
  "product_id": "YOUR_PRODUCT_ID",
  "webhook_secret": "YOUR_WEBHOOK_SECRET",
  "integration_type": "zendesk",
  "integration_config": {
    "subdomain": "YOUR_SUBDOMAIN",
    "email": "YOUR_ZENDESK_EMAIL",
    "api_token": "YOUR_API_TOKEN"
  }
}
```

---

## Preflight — verify credentials before touching anything

Run this and bail on failure. Do not proceed until this passes.

```python
import base64, os
import httpx

subdomain = os.environ["ZENDESK_SUBDOMAIN"]
email     = os.environ["ZENDESK_EMAIL"]
api_token = os.environ["ZENDESK_API_TOKEN"]

creds   = base64.b64encode(f"{email}/token:{api_token}".encode()).decode()
headers = {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}
base    = f"https://{subdomain}.zendesk.com/api/v2"

async with httpx.AsyncClient(base_url=base) as client:
    r = await client.get("/users/me.json", headers=headers)
    assert r.status_code == 200, f"Auth failed ({r.status_code}): {r.text}"
    me = r.json()["user"]
    assert me["role"] in ("admin", "agent"), f"Need admin/agent role, got: {me['role']}"
    print(f"✓ Authenticated as {me['email']} (role={me['role']})")
```

**If 401:** confirm "Allow API token access" is checked in Admin Center → APIs →
**API configuration**. Also confirm `ZENDESK_EMAIL` is an active admin or agent.

---

## Step 1 — Register two webhooks + two triggers in Zendesk

Two webhooks are required — one per connector endpoint.

**Critical:**
- Trigger A body: `trigger_type=new_ticket` — no user message needed.
- Trigger B body: include `"user_message": "{{ticket.latest_comment}}"` so the
  connector receives the message text directly. Zendesk Messaging tickets do not
  store messages as public ticket comments, so fetching via the comments API
  would return empty. The inline payload field is the only reliable source.

```python
import base64, json, os
import httpx

subdomain      = os.environ["ZENDESK_SUBDOMAIN"]
email          = os.environ["ZENDESK_EMAIL"]
api_token      = os.environ["ZENDESK_API_TOKEN"]
product_id     = os.environ["AUTOPLAY_PRODUCT_ID"]
connector_url  = os.environ["CONNECTOR_URL"]  # from autoplay-core setup

creds   = base64.b64encode(f"{email}/token:{api_token}".encode()).decode()
headers = {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}
base    = f"https://{subdomain}.zendesk.com/api/v2"

context_endpoint = f"{connector_url.rstrip('/')}/chatbot-webhook/{product_id}"
chat_endpoint    = f"{connector_url.rstrip('/')}/zendesk/chat/{product_id}"


async with httpx.AsyncClient(base_url=base) as client:

    print(f"About to register Autoplay webhooks in {subdomain}.zendesk.com")
    print(f"  Context endpoint: {context_endpoint}")
    print(f"  Chat endpoint:    {chat_endpoint}")
    confirm = input("Confirm? [y/n] ")
    if confirm.lower() != "y":
        raise SystemExit("Aborted")

    def _create_webhook(name, endpoint):
        return client.post(
            "/webhooks", headers=headers,
            json={"webhook": {
                "name": name,
                "endpoint": endpoint,
                "http_method": "POST",
                "request_format": "json",
                "status": "active",
                "subscriptions": ["conditional_ticket_events"],
            }},
        )

    # 1a — Context webhook → /chatbot-webhook (session link + internal note)
    r = await _create_webhook("Autoplay Context Webhook", context_endpoint)
    r.raise_for_status()
    context_webhook_id = r.json()["webhook"]["id"]
    print(f"✓ Context webhook created: {context_webhook_id}")

    # 1b — Chat webhook → /zendesk/chat (LLM reply)
    r = await _create_webhook("Autoplay Chat Webhook", chat_endpoint)
    r.raise_for_status()
    chat_webhook_id = r.json()["webhook"]["id"]
    print(f"✓ Chat webhook created: {chat_webhook_id}")

    # 1c — Trigger A: new ticket → context webhook (internal note only, no reply)
    trigger_a_body = json.dumps({
        "ticket_id":       "{{ticket.id}}",
        "requester_email": "{{ticket.requester.email}}",
        "trigger_type":    "new_ticket",
    })
    r = await client.post("/triggers", headers=headers, json={"trigger": {
        "title": "Autoplay — New Ticket", "active": True,
        "conditions": {"all": [
            {"field": "update_type", "operator": "is", "value": "Create"},
        ]},
        "actions": [{"field": "notification_webhook",
                     "value": [context_webhook_id, trigger_a_body]}],
    }})
    r.raise_for_status()
    print(f"✓ Trigger A (New Ticket): {r.json()['trigger']['id']}")

    # 1d — Trigger B: user reply → chat webhook (LLM reply)
    # Include user_message inline — required for Zendesk Messaging tickets
    # where the comments API returns no public comments.
    # Note: role:end-user condition silently fails for Messaging — omit it.
    trigger_b_body = json.dumps({
        "ticket_id":       "{{ticket.id}}",
        "requester_email": "{{ticket.requester.email}}",
        "trigger_type":    "user_reply",
        "user_message":    "{{ticket.latest_comment}}",
    })
    r = await client.post("/triggers", headers=headers, json={"trigger": {
        "title": "Autoplay — User Reply", "active": True,
        "conditions": {"all": [
            {"field": "update_type",       "operator": "is", "value": "Change"},
            {"field": "comment_is_public", "operator": "is", "value": "true"},
        ]},
        "actions": [{"field": "notification_webhook",
                     "value": [chat_webhook_id, trigger_b_body]}],
    }})
    r.raise_for_status()
    print(f"✓ Trigger B (User Reply): {r.json()['trigger']['id']}")
```

Confirm in Zendesk Admin Center:
- **Apps and integrations → Webhooks** — both "Autoplay Context Webhook" and
  "Autoplay Chat Webhook" show Active
- **Objects and rules → Triggers** — both Autoplay triggers show Active

---

## Step 2 — Smoke test

Ask the customer to:
1. Open their product in a browser with PostHog running and `posthog.identify()` called
2. Perform 2–3 actions (page views, button clicks)
3. Open the Zendesk widget → send a message (this creates the ticket)
4. Wait ~10 seconds, then send a follow-up message in the widget

**Verify internal note (Trigger A result):**

```bash
curl -u "$ZENDESK_EMAIL/token:$ZENDESK_API_TOKEN" \
  "https://$ZENDESK_SUBDOMAIN.zendesk.com/api/v2/tickets/recent.json" \
  | python3 -c "import sys,json; t=json.load(sys.stdin)['tickets'][0]; print(t['id'], t['subject'])"
```

Take the ticket ID and check for the internal note:

```bash
curl -u "$ZENDESK_EMAIL/token:$ZENDESK_API_TOKEN" \
  "https://$ZENDESK_SUBDOMAIN.zendesk.com/api/v2/tickets/{TICKET_ID}/comments.json" \
  | python3 -c "
import sys, json
for c in json.load(sys.stdin)['comments']:
    tag = '[INTERNAL NOTE]' if not c['public'] else '[PUBLIC REPLY]'
    print(tag, c['body'][:200])
"
```

Expected output — internal note with event context AND a public Claude reply:

```
[INTERNAL NOTE] session_id: ps_abc123
timestamp: 2026-06-04 14:30:00 UTC

[1] Visited /dashboard — User landed on the Dashboard
[2] Clicked Export — User clicked the Export button

[PUBLIC REPLY] Thanks for reaching out! Based on what I can see, you were
exploring the dashboard and tried to export data. Here's how I can help...
```

If both appear within 15 seconds, the integration is complete. ✓

**Quick curl test (without widget):**

```bash
# Test internal note + session link (Trigger A)
curl -X POST "$CONNECTOR_URL/chatbot-webhook/$AUTOPLAY_PRODUCT_ID" \
  -H "Content-Type: application/json" \
  -d '{"ticket_id":"TICKET_ID","requester_email":"USER_EMAIL","trigger_type":"new_ticket"}'

# Test LLM reply (Trigger B) — use an existing ticket with a user message
curl -X POST "$CONNECTOR_URL/zendesk/chat/$AUTOPLAY_PRODUCT_ID" \
  -H "Content-Type: application/json" \
  -d '{"ticket_id":"TICKET_ID","requester_email":"USER_EMAIL","trigger_type":"user_reply","user_message":"Hello, I need help with exporting data"}'
```

Both should return `{"status": "accepted", ...}`. Check the ticket for the
internal note and public reply.

---

## Failure modes and exact fixes

**1 — 401 on preflight**
"Allow API token access" must be checked in Admin Center → APIs → API configuration.
`ZENDESK_EMAIL` must match an active admin or agent on this account.
Auth format is `{email}/token:{api_token}` — the `/token` literal is required.

**2 — Triggers never fire (webhook Activity tab empty)**
Webhook must be created with `subscriptions: ["conditional_ticket_events"]`.
Without this, Triggers cannot reference the webhook. Delete and re-run Step 1.

**3 — No internal note at all after 30 seconds**
The connector never received Trigger A. Check:
- Webhook Activity tab in Zendesk — did any requests fire?
- If yes: confirm `CONNECTOR_URL` points at the live Autoplay connector
- If no: confirm Trigger A is Active and its condition matches the ticket type

**4 — Internal note has no actions (header only)**
`posthog.identify()` has not fired yet, or the user created the ticket before
doing any actions. The buffer was empty at flush time. Ensure `identify()` is
called and the user performs actions before opening a support ticket.

**5 — No Claude public reply after user sends follow-up message**
Trigger B may not be configured or the `user_message` field is missing.
Verify Trigger B's webhook body contains `"user_message": "{{ticket.latest_comment}}"`.
Also confirm Trigger B points at the Chat Webhook (`/zendesk/chat/...`), not the
Context Webhook.

**6 — Trigger B never fires for Zendesk Messaging tickets**
`role: end-user` condition silently fails for Zendesk Messaging.
Only use `update_type: Change` + `comment_is_public: true` — no role condition.

**7 — `session_linked: false` in the `/zendesk/chat` response**
The connector could not find a PostHog session for the ticket's requester email.
Causes:
- The user was anonymous in the widget (no email passed) — implement Zendesk
  Identity Verification to pass a signed JWT with the user's email.
- `posthog.identify()` used a different identifier than the Zendesk email.
  Ensure `distinct_id` in PostHog matches the email Zendesk sends in
  `{{ticket.requester.email}}`.
The LLM reply will still be posted but without PostHog event context.

**8 — Zendesk Messaging: `no public user message found` in connector logs**
This happens when Trigger B does NOT include `user_message` in its body, and
the connector falls back to the comments API which returns only internal notes
for Messaging tickets. Fix: update Trigger B body to include
`"user_message": "{{ticket.latest_comment}}"` (see Step 1).

**9 — 503 "no live worker" from connector**
The `ZendeskChatbot` worker failed to start — usually a misconfigured
`integration_type`. Confirm the product is registered with
`integration_type=zendesk` (not `event_stream`) in `PRODUCTS_CONFIG`.

---

## Reference

- Zendesk Webhooks API: https://developer.zendesk.com/api-reference/webhooks/webhooks-api/webhooks/
- Zendesk Triggers API: https://developer.zendesk.com/api-reference/ticketing/business-rules/triggers/
- Zendesk Identity Verification: https://developer.zendesk.com/documentation/zendesk-web-widget-sdks/sdks/web/enabling_auth_visitors/
- Autoplay core skill: `autoplay-core`