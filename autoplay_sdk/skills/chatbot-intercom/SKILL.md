---
skill: chatbot-intercom
family: chatbot
version: 0.5.0
sdk_min: 0.11.0
tags: [intercom, fin, mcp]
name: chatbot-intercom
description: >-
  Connects an existing Intercom Fin workspace to Autoplay live activity through the
  Autoplay MCP server. Covers adding the MCP connector, enabling the Get Live User
  Activity tool, configuring Bearer token authentication, and using Messenger JWT
  identity so Fin asks for the right user's activity. Use when the customer already uses
  Intercom, Fin, Custom MCP, Messenger JWT identity, or asks how to give Fin real-time
  Autoplay context.
disable-model-invocation: true
---


# AI Support Agent — Intercom Fin

> Read `autoplay-core` first for install and credentials (`product_id`, `mcp_url`, `mcp_key`). This skill assumes the customer already uses Intercom Fin; do not guide them through installing Intercom from scratch.

## Current integration path

Intercom Fin pulls a user's recent in-app activity on demand through the **Autoplay MCP server**. Fin calls the `Get Live User Activity` tool only when it needs context to answer a user's question.

Use this path for reactive Q&A:

1. Register or confirm the customer's Autoplay product so you have `product_id`, `mcp_url`, and `mcp_key`.
2. Add the Autoplay MCP server in Intercom under **Settings -> Integrations -> Data connectors -> Custom MCP**.
3. Configure Bearer token authentication with the `mcp_key` from `onboard_product`.
4. Enable the `Get Live User Activity` tool.
5. Configure Messenger JWT identity so Fin passes the same stable user id that the activity source uses.
6. Test with a logged-in user who has clicked around the app, then ask Fin a question that needs recent in-app context.

There is no webhook, no `conv_map`, no `BaseChatbotWriter`, and no admin-note stream in the default Fin integration.

## Identity requirement

The MCP read is keyed by `product_id` + `user_id`. The `user_id` Fin sends must exactly match the id emitted by the customer's activity source:

- PostHog: the value passed to `posthog.identify(user.id)`
- Amplitude: the value passed to `amplitude.setUserId(user.id)`
- FullStory: the stable user/session identifier configured in the FullStory stream

If those identifiers differ, Fin can connect to the MCP server successfully but still receive empty live activity.

## Intercom MCP checklist

In Intercom:

- **Connector type:** Custom MCP
- **Server URL:** `https://mcp.autoplay.ai/mcp`
- **Authentication:** Bearer token
- **Token value:** `YOUR_MCP_KEY` without the `Bearer ` prefix if Intercom has a separate prefix field
- **Tool:** `Get Live User Activity`
- **Product id / external id:** the `product_id` printed by `onboard_product`

Use the exact values from the Autoplay product registration. Do not mint separate Intercom-only product ids.

## Prompt guidance

Fin should call the tool when the answer depends on what the user recently did in the app, for example:

- the user says they are stuck but does not name the screen
- the user asks why a button or workflow is not working
- the user asks for next-step guidance after navigating through the product
- the user asks about a recent action, page, or failed attempt

Fin should not call the tool for generic policy, pricing, account, or documentation questions that do not require live user activity.

## Troubleshooting

- **401 / Unauthorized:** the MCP key is missing, wrong, or includes a duplicate `Bearer ` prefix.
- **403 / product mismatch:** the Intercom tool's product/external id does not match the registered Autoplay `product_id`.
- **Empty activity:** the `user_id` from Messenger JWT does not match the user id from the activity source, or the user has not generated recent tracked activity.
- **Tool never called:** the tool description/prompt does not clearly tell Fin when live activity is relevant.
- **MCP connector unavailable:** Intercom Custom MCP availability can depend on workspace capabilities and hosting region; follow the current tutorial for the latest workspace prerequisites.

## Reference

- Full tutorial: https://developers.autoplay.ai/recipes/intercom-tutorial
- MCP server docs: https://developers.autoplay.ai/mcp/server
