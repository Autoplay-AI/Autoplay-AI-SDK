---
skill: chatbot-template
family: chatbot
version: 0.1.0
sdk_min: 0.11.0
tags: [platform, mcp, live-activity]
name: chatbot-template
description: >-
  Template for connecting an existing AI support agent to Autoplay live activity.
  Replace [PLATFORM] with the customer platform and prefer the MCP pull pattern
  whenever the platform can call MCP tools or make authenticated HTTP requests.
disable-model-invocation: true
---

# AI Support Agent — [PLATFORM NAME]

> Read `autoplay-core` first for Autoplay install and credentials (`product_id`, `mcp_url`, `mcp_key`). This template assumes the customer already uses [PLATFORM]; do not guide them through adopting [PLATFORM] from scratch.

## Current integration path

Prefer the pull-based MCP pattern:

```
User does actions in the product
        ↓
Existing activity source sends events to Autoplay
        ↓
User asks [PLATFORM] AI agent for help
        ↓
[PLATFORM] calls Autoplay MCP tool get_live_user_activity
        ↓
Agent answers with recent in-app context
```

There is no customer-hosted server, webhook session-linking layer, or internal-note stream unless the platform cannot call tools at answer time.

## Credentials and identifiers

Collect or confirm:

- `product_id` from Autoplay product registration
- `mcp_url`, usually `https://mcp.autoplay.ai/mcp`
- `mcp_key` from Autoplay product registration
- the stable `user_id` field [PLATFORM] can pass to the MCP tool

The `user_id` must exactly match the id emitted by the activity source. Do not use anonymous browser ids, conversation ids, ticket ids, or emails unless that is also the activity source identifier.

## Step 1 — Add the Autoplay MCP server

In [PLATFORM], add a custom MCP server or equivalent external tool:

- **Server URL:** `https://mcp.autoplay.ai/mcp`
- **Authentication:** Bearer token
- **Token value:** `YOUR_MCP_KEY`
- **Tool:** `get_live_user_activity` / `Get Live User Activity`

If [PLATFORM] does not support MCP directly, use the smallest platform-native action/API-call primitive that can make an authenticated request to Autoplay's live-activity read endpoint.

## Step 2 — Wire identity

Pass the current logged-in user's stable id to the tool call as `user_id`.

Examples:

- PostHog source: match `posthog.identify(user.id)`
- Amplitude source: match `amplitude.setUserId(user.id)`
- FullStory source: match the configured FullStory user identifier

## Step 3 — Prompt the agent to use the tool

Tell [PLATFORM] to call the live-activity tool when the answer depends on recent in-app behavior:

- the user is stuck but did not name the exact screen
- the user asks what to do next after navigating through the app
- the user asks about a button, workflow, or recent failed attempt
- the user asks for guidance that should adapt to what they just did

Do not call the tool for generic product, billing, account, or policy questions.

## Step 4 — Test

1. Log in as a known user.
2. Generate recent activity in the app.
3. Ask [PLATFORM] a question that needs that recent activity.
4. Confirm the agent calls Autoplay and uses the returned context in the answer.

## Failure modes

- **401:** wrong `mcp_key` or duplicate `Bearer ` prefix.
- **403:** product id does not match the token/external id expected by the connector.
- **Empty activity:** user id mismatch or no recent tracked activity.
- **Tool not called:** the tool description or agent prompt is too vague.
- **Platform cannot call MCP:** use REST live-activity read as a bridge, then document the bridge as platform-specific.

## Reference

- Autoplay MCP server: https://developers.autoplay.ai/mcp/server
- Autoplay core skill: `autoplay-core`
- [PLATFORM] MCP/tool docs: [URL]
