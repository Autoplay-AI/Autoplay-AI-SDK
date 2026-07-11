---
skill: chatbot-tidio
family: chatbot
version: 0.1.0
sdk_min: 0.7.1
tags: [tidio, lyro, mcp]
name: chatbot-tidio
description: >-
  Connects an existing Tidio Lyro AI agent to Autoplay live activity with a Lyro Action
  that calls the Autoplay MCP server. Covers creating the action, passing a stable
  visitor user ID, and letting Lyro pull recent activity on demand. Use when the
  customer already uses Tidio, Lyro, Tidio Actions, or asks how to give Lyro real-time
  Autoplay context.
disable-model-invocation: true
---

# AI Support Agent — Tidio

> Read `autoplay-core` first for install and credentials (`product_id`, `mcp_url`, `mcp_key`).

## Scoping pattern for Tidio

Lyro (Tidio's AI agent) pulls a user's live activity on demand via a **Lyro Action** that calls the Autoplay MCP server — no webhook, no session-linking, no `conv_map`. The read is keyed by `product_id` + `user_id` only.

Set the user's stable id via `window.tidioChatApi.setVisitorData({ custom: { user_id: currentUser.id } })` after login so `{{contact.user_id}}` is available to the Action — it must exactly equal the id your activity source identifies the user with. See the full tutorial for the Action/API-call setup and identity wiring.

## Reference

- Tutorial: https://developers.autoplay.ai/recipes/tidio
