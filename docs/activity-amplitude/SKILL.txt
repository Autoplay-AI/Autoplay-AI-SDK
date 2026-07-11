---
skill: activity-amplitude
family: activity
version: 0.1.0
sdk_min: 0.11.0
tags: [amplitude, event-streaming, mcp]
name: activity-amplitude
description: >-
  Connects an existing Amplitude project to Autoplay live activity using the
  @amplitude/unified SDK and Amplitude HTTP Event Streaming. Covers verifying
  autocapture and stable user IDs, running onboard_product for ingest and MCP
  credentials, and pointing Amplitude's event stream at Autoplay. Use when the customer
  already uses Amplitude, @amplitude/unified, amplitude.init, amplitude.setUserId, or
  asks how to send Amplitude activity to Autoplay.
disable-model-invocation: true
---

# Session Replay Provider — Amplitude

> Read `autoplay-core` first for Autoplay install, credentials, and the pull-based read pattern. This skill assumes the customer already uses Amplitude; do not guide them through adopting Amplitude from scratch.

## Step 1 — Verify the existing Amplitude SDK

Confirm the app is using `@amplitude/unified` with Analytics and Session Replay enabled. If the customer is still on the older `@amplitude/analytics-browser` package, treat that as a customer migration decision and call it out before changing dependencies.

---

## Step 2 — Verify initialization on app load

```javascript
import * as amplitude from '@amplitude/unified';

amplitude.initAll('YOUR_AMPLITUDE_API_KEY', {
  analytics: { autocapture: true },   // required — captures clicks, page views, forms
  sessionReplay: { sampleRate: 1 },
});
```

This should already run once at app startup. `autocapture: true` is required — without it no click/pageview events reach Autoplay.

---

## Step 3 — Identify on login (required for user scoping)

```javascript
amplitude.setUserId(user.id);   // the stable id the live-activity read is keyed by

const identifyObj = new amplitude.Identify();
identifyObj.set('email', user.email);
identifyObj.set('name', user.name);
amplitude.identify(identifyObj);

// On logout:
amplitude.reset();
```

Without `setUserId`, events carry only a `device_id` — Autoplay still records activity, but no agent can look the user up by their real id. `amplitude.identify()` (email/name) is optional enrichment on top.

---

## Step 4 — Register with Autoplay

```python
import asyncio
from autoplay_sdk.admin import onboard_product
from autoplay_sdk.providers import AmplitudeProvider

async def main() -> None:
    result = await onboard_product(
        "YOUR_AMPLITUDE_PROJECT_ID",
        contact_email="you@yourcompany.com",
        user_activity_provider=AmplitudeProvider(),
        print_operator_summary=True,
    )

asyncio.run(main())
```

Prints six values — save them:
- `product_id`, `provider` (`amplitude`)
- `ingest_url` — e.g. `https://connector.autoplay.ai/ingest/YOUR_AMPLITUDE_PROJECT_ID`
- `ingest_secret` — Amplitude sends this as `Authorization: Bearer <ingest_secret>`
- `mcp_url` — always `https://mcp.autoplay.ai/mcp`
- `mcp_key` — Bearer token for the agent's live-activity read (REST or MCP)

There is no more `stream_url` / `unkey_key` / `amplitude_ingest_url` — those were legacy Render fields.

---

## Step 5 — Create the Amplitude Event Streaming destination

**Data → Destinations → + Add Destination → search "HTTP" → Event Streaming.**

| Field | Value |
|---|---|
| URL Endpoint (method `POST`) | `ingest_url` from Step 4 |
| Create Parameters → `apiKey` | `Bearer ` + `ingest_secret` from Step 4 |
| REST API Headers → `Authorization` | `${parameters.apiKey}` |

**Event Body Editor** — paste this Freemarker template exactly (do not use Amplitude's default template — it drops clicks and form events, only page views survive):

```
<#setting number_format="0.####">
<#assign et = input.event_type!''>
<#assign ep = input.event_properties!{}>
<#assign up = input.user_properties!{}>

{
  "events": [
    {
      "event_type": "<#if et?starts_with('Viewed') || et == '[Amplitude] Page Viewed' || et == 'Page Viewed'>$pageview<#elseif et == '[Amplitude] Element Clicked' || et == '[Amplitude] Element Changed' || et?starts_with('Form')>$autocapture<#else>${et}</#if>",
      "user_id": "${input.user_id!''}",
      "device_id": "${input.device_id!''}",
      "session_id": ${input.session_id!0},
      "time": ${input.time!0},
      "user_properties": {
        <#list up?keys as k>"${k}": "${up[k]}"<#sep>, </#sep></#list>
      },
      "event_properties": {
        "[Amplitude] Page URL": "${ep['Page URL']!ep['Page Location']!ep['[Amplitude] Page URL']!ep['[Amplitude] Page Location']!''}",
        "[Amplitude] Page Title": "${ep['Page Title']!ep['[Amplitude] Page Title']!''}",
        "$event_type": "<#if et == '[Amplitude] Element Changed'>change<#elseif et?starts_with('Form Submitted')>submit<#elseif et?starts_with('Form Started')>focus<#else>click</#if>",
        "$current_url": "${ep['Page URL']!ep['Page Location']!ep['[Amplitude] Page URL']!ep['[Amplitude] Page Location']!''}",
        "$button_text": "${ep['[Amplitude] Element Text']!ep['Element Text']!ep['Page Title']!''}",
        "$elements_chain": "${ep['[Amplitude] Element Path']!ep['[Amplitude] Element Hierarchy']!ep['Element Path']!''}",
        "$element_id": "${ep['[Amplitude] Element ID']!ep['Element ID']!''}",
        "$element_tag": "${ep['[Amplitude] Element Tag']!ep['Element Tag']!''}"
      }
    }
  ]
}
```

On the Testing tab: enable **Send Events**, keep **All Events**, click **Test Connection** (expect `200 OK`), then **Release** and create a Sync.

---

## Step 6 — Verify

```bash
curl "https://mcp.autoplay.ai/users/YOUR_AMPLITUDE_PROJECT_ID/YOUR_USER_ID/live-activity?limit=10" \
  -H "Authorization: Bearer YOUR_MCP_KEY"
```

`YOUR_USER_ID` is the id passed to `amplitude.setUserId(...)`. A `200` with a populated `actions` array confirms events are flowing — this is the same pull-based read every agent uses, over REST or MCP.

If `401`: confirm the destination's `Authorization` header is `Bearer <ingest_secret>` and the URL is `ingest_url` exactly. If `404`/empty: confirm `YOUR_AMPLITUDE_PROJECT_ID` matches the `product_id` used at registration, and that you're querying the same id set via `setUserId`.

---

## Common mistakes

**Not calling `amplitude.setUserId()` on login.** This is the call that stamps the top-level `user_id` the connector keys activity by. Without it, events carry only a `device_id`.

**Using the default Amplitude template instead of the Freemarker one above.** Only page views arrive; clicks and form events are silently dropped.

**Session ID is `-1` in early events.** Normal — Amplitude initializes it before the first session is established. The connector falls back to `device_id` for those events; resolves within seconds.

---

## Reference

- Quickstart: https://developers.autoplay.ai/quickstart
- Amplitude Unified SDK docs: https://amplitude.com/docs/sdks/analytics/browser/browser-sdk-2
- Amplitude HTTP destination docs: https://amplitude.com/docs/data/destination-catalog/http
