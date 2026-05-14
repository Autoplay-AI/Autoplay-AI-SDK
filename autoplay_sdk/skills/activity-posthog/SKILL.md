---
name: activity-posthog
description: >-
  Configures PostHog as the event source for Autoplay by adding the browser snippet,
  calling posthog.identify() with product_id, and setting up the PostHog webhook
  destination. The PostHog session ID is the scoping key used throughout the
  Autoplay integration. Use when the user mentions PostHog, posthog-js, posthog.identify,
  product_id, or asks how to capture user events for Autoplay.
disable-model-invocation: true
---

# Activity Source — PostHog

> Read `autoplay-core` first. The PostHog `session_id` is the `session_id` used
> for all session scoping throughout your Autoplay integration.

## Step 1 — Add the browser snippet

```javascript
import posthog from 'posthog-js'

posthog.init('YOUR_AUTOPLAY_API_KEY', {
    api_host: 'https://us.i.posthog.com',
    person_profiles: 'identified_only',
    session_idle_timeout_seconds: 120,
    loaded: (posthog) => {
        posthog.identify(posthog.get_distinct_id(), {
            product_id: 'YOUR_PRODUCT_ID',
        });
    },
})
```

---

## Step 2 — Identify on login (highly recommended)

Run this immediately after your login flow completes:

```javascript
posthog.identify(user.id, {
    product_id: 'YOUR_AUTOPLAY_PRODUCT_ID',
    email: user.email,  // optional but enables email-based session scoping
})
```

Without `identify`, users are tracked anonymously. `session_id` still works for scoping; `user_id` and `email` will be `None` on `ActionsPayload` until identity is set.

---

## Step 3 — Session ID in your backend

```python
# The session_id on every ActionsPayload is the PostHog session ID
# Retrieve it in browser:
#   posthog.get_distinct_id()   — stable user/device ID
#   posthog.get_session_id()    — current session ID (resets on idle)

# Guard for None before identity linking:
async def on_actions(payload):
    if not payload.session_id:
        return   # anonymous pre-identity event — skip or queue
    await agent_writer.add(payload)
```

---

## Step 4 — PostHog webhook destination

In PostHog, add a **Webhook** destination:
- **Webhook URL:** `result.webhook_url` from `onboard_product`
- **`X-PostHog-Secret` header:** `result.webhook_secret` from `onboard_product`

Or message `#just-integrated` in the Autoplay Slack for managed setup.

---

## Reference

- Quickstart: https://developers.autoplay.ai/quickstart
- PostHog identify docs: https://posthog.com/docs/product-analytics/identify
