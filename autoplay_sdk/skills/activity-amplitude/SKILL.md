---
name: activity-amplitude
description: >-
  Configures Amplitude as the event source for Autoplay by installing the
  Amplitude Browser SDK, calling amplitude.setUserId() and amplitude.identify()
  with product_id, and setting up an Amplitude HTTP destination to stream events
  to the Autoplay connector. The Amplitude session_id is the scoping key used
  throughout the Autoplay integration. Use when the user mentions Amplitude,
  @amplitude/analytics-browser, amplitude.init, amplitude.identify, or asks how
  to capture user events for Autoplay using Amplitude.
disable-model-invocation: true
---

# Activity Source — Amplitude

> Read `autoplay-core` first. The Amplitude `session_id` (from
> `amplitude.getSessionId()`) is the `session_id` used for all session scoping
> throughout your Autoplay integration.

## Step 1 — Install the Amplitude Browser SDK

```bash
npm install @amplitude/analytics-browser
```

---

## Step 2 — Initialize on app load

```typescript
import * as amplitude from '@amplitude/analytics-browser';

amplitude.init('YOUR_AMPLITUDE_API_KEY', undefined, {
  defaultTracking: {
    sessions: true,
    pageViews: true,
    formInteractions: true,
    fileDownloads: true,
  },
});
```

Call this once at app startup (e.g. `main.ts`, `_app.tsx`, or your root layout).
`defaultTracking` ensures page views and session events flow to Autoplay automatically.

---

## Step 3 — Identify on login (required for session scoping)

Run this immediately after your login flow completes:

```typescript
import { Identify } from '@amplitude/analytics-browser';

amplitude.setUserId(user.id);

const identify = new Identify()
  .set('product_id', 'YOUR_AMPLITUDE_PROJECT_ID')  // your Amplitude project ID — Settings → Projects → Project ID
  .set('email', user.email);       // optional but enables email-based lookup
amplitude.identify(identify);
```

`YOUR_AMPLITUDE_PROJECT_ID` is your **Amplitude project ID** (a numeric string found in Amplitude under
**Settings → Projects → select your project → Project ID**). This is NOT an ID that Autoplay assigns — you
supply it yourself, and it becomes your Autoplay `product_id`.

Without `setUserId`, users are tracked by `device_id` only. `session_id` still
works for scoping; `user_id` and `email` will be `None` on `ActionsPayload` until
identity is set.

---

## Step 4 — Session ID in your backend

```python
# The session_id on every ActionsPayload is the Amplitude session_id
# (as a string, e.g. "1749000000000").
# Retrieve the current session in browser:
#   amplitude.getSessionId()   — current session ID (Unix ms, resets on idle)
#   amplitude.getUserId()      — identified user ID (set via setUserId)
#   amplitude.getDeviceId()    — stable device ID (fallback session key)

# Guard for None before identity linking:
async def on_actions(payload):
    if not payload.session_id:
        return   # session not yet established — skip or queue
    await agent_writer.add(payload)
```

---

## Step 5 — Configure the Amplitude HTTP destination

The Autoplay Amplitude ingest URL is derived from your connector stream URL:

```python
# From onboard_product result:
# stream_url   = "https://your-connector.onrender.com/stream/YOUR_PRODUCT_ID"
# ingest_url   = "https://your-connector.onrender.com/ingest/amplitude/YOUR_PRODUCT_ID"

amplitude_ingest_url = result.stream_url.replace("/stream/", "/ingest/amplitude/")
amplitude_bearer_token = result.unkey_key
```

In Amplitude: **Data → Catalog → Destinations → Create New Destination → Event Streaming**

| Field | Value |
|-------|-------|
| Destination Name | `autoplay-event-stream` |
| Endpoint URL | `https://your-connector.onrender.com/ingest/amplitude/YOUR_PRODUCT_ID` |
| Authentication | Bearer Token |
| Token | `result.unkey_key` from `onboard_product` |
| Events to send | All events (or filter to page/click events) |

Or message `#just-integrated` in the Autoplay Slack for managed setup.

---

## Step 6 — Verify the destination is firing

After creating the destination, trigger a page view in your app and check:
**Amplitude → Data → Connections → your destination → Delivery metrics**

You should see a successful delivery within a few seconds.

If you see `401`:
- Confirm the Bearer token is `result.unkey_key` (not `result.webhook_secret`).
- Confirm the destination URL ends with `/ingest/amplitude/YOUR_PRODUCT_ID` (not `/webhook/`).

If you see `404`:
- Confirm `YOUR_PRODUCT_ID` in the URL matches the `product_id` used in `onboard_product`.

If you see no deliveries at all:
- Confirm the destination is enabled and the event filter is not excluding all events.

---

## Common mistakes

**Using `result.webhook_url` instead of the Amplitude ingest URL.**
`webhook_url` is the PostHog endpoint — it expects a PostHog-signed payload and
will return `401` for Amplitude events. Always use `/ingest/amplitude/{product_id}`.

**Calling `amplitude.setUserId()` but not `amplitude.identify()` with `product_id`.**
`setUserId` alone does not set user properties. Call `amplitude.identify()` with
an `Identify` object to set `product_id` in `user_properties` so identity lookups
work when a chatbot webhook arrives.

**Session ID is `-1`.**
Amplitude sets `session_id = -1` before the first session is established (e.g.
immediately on page load before the session timer fires). The Autoplay connector
falls back to `device_id` in this case, which is still a valid scoping key.

---

## Reference

- Quickstart: https://developers.autoplay.ai/quickstart
- Amplitude Browser SDK docs: https://amplitude.com/docs/sdks/analytics/browser/browser-sdk-2
- Amplitude HTTP destination docs: https://amplitude.com/docs/data/destination-catalog/http
