---
name: activity-fullstory
description: >-
  Configures a FullStory Stream to fire a webhook to Autoplay on every user click,
  capturing target text, page URL, timestamp, and session ID. Everything is configured
  in the FullStory dashboard — no frontend code changes required. Use when the user
  mentions FullStory, FullStory Streams, Anywhere Activation, or asks how to stream
  user click events from FullStory into Autoplay.
disable-model-invocation: true
---

# Activity Source — FullStory Streams

> Read `autoplay-core` first — the `session_id` in the FullStory payload maps directly
> to the Autoplay `session_id` used for session scoping.

## Prerequisites

- FullStory installed and capturing sessions (`FS('getSession')` returns a URL)
- Enterprise or Advanced FullStory plan (Streams requires Anywhere: Activation)
- Admin or Architect role in FullStory
- Autoplay ingest endpoint URL and auth token

---

## Step 1 — Create the Stream

In FullStory: **Settings → Anywhere → Activation → Create Stream**

- **Name:** `autoplay-every-click`
- **Description:** `Streams every user click event to the Autoplay SDK`

---

## Step 2 — Configure destination

| Field | Value |
|-------|-------|
| Destination type | HTTP Endpoint |
| Request Method | POST |
| API Endpoint URL | Your Autoplay ingest URL |
| Authentication | Bearer token |

---

## Step 3 — Define the trigger

1. Click **Select an event** → choose **Element Clicked**
2. Add **no filters** — empty = every click
3. Frequency: **On every event** (not "Once per session" — that only fires once per user session)

---

## Step 4 — JSON field mapping

Switch to **JSON view** in Field Mapping and paste:

```json
{
  "target_text":        ["var", "event.0.target_text"],
  "element_name":       ["var", "event.0.element_name"],
  "page_url":           ["var", "event.0.url"],
  "timestamp":          ["var", "event.0.event_time"],
  "timestamp_unix":     ["toUnixTimestamp", ["var", "event.0.event_time"]],
  "session_replay_url": ["var", "event.0.app_url_event"],
  "user_id":            ["var", "event.0.user_id"],
  "user_email":         ["var", "event.0.user_email"],
  "session_id":         ["concat", ["var", "event.0.device_id"], "%3A", ["var", "event.0.session_id"]]
}
```

`session_id` here is the key used for session scoping in `autoplay-core` — use it as the `session_id` bucket key throughout.

---

## Step 5 — Test and save

1. Click **Send Test** — confirm `200 OK` under Server Response
2. Click **Save**

---

## IP allowlist

Whitelist these on your Autoplay endpoint:
- **US:** `8.35.195.0/29`
- **EU:** `34.89.210.80/29`

FullStory retries failed requests (5xx / timeout) up to 30 times over 5 hours.

---

## Reference

- Full tutorial: https://developers.autoplay.ai/recipes/fullstory
- FullStory Streams docs: https://developer.fullstory.com/anywhere/activation/streams/
