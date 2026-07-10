---
name: chatbot-tidio
description: >-
  Wires the Autoplay SDK into Tidio for real-time user context. Use when the
  user mentions Tidio or asks how to give their Tidio chatbot real-time
  context from Autoplay.
disable-model-invocation: true
---

# Chatbot — Tidio

> Read `autoplay-core` first for install and credentials (`product_id`, `mcp_url`, `mcp_key`).

## Scoping pattern for Tidio

Lyro (Tidio's AI agent) pulls a user's live activity on demand via a **Lyro Action** that calls the Autoplay MCP server — no webhook, no session-linking, no `conv_map`. The read is keyed by `product_id` + `user_id` only.

Set the user's stable id via `window.tidioChatApi.setVisitorData({ custom: { user_id: currentUser.id } })` after login so `{{contact.user_id}}` is available to the Action — it must exactly equal the id your activity source identifies the user with. See the full tutorial for the Action/API-call setup and identity wiring.

## Reference

- Tutorial: https://developers.autoplay.ai/recipes/tidio
