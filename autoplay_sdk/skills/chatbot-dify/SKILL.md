---
skill: chatbot-dify
family: chatbot
version: 0.2.0
sdk_min: 0.7.1
tags: [dify, mcp, live-activity]
name: chatbot-dify
description: >-
  Connects an existing Dify Agent to Autoplay live activity through the Autoplay MCP
  server. Covers adding the MCP server under Tools, enabling get_live_user_activity, and
  passing a stable user_id input that matches the activity source. Use when the customer
  already uses Dify, Dify Agent, Dify MCP, or asks how to give Dify real-time Autoplay
  context.
disable-model-invocation: true
---

# AI Support Agent — Dify

> Read `autoplay-core` first for install and credentials (`product_id`, `mcp_url`, `mcp_key`).

## Scoping pattern for Dify

The Dify Agent pulls a user's live activity on demand via an **Autoplay MCP server** added under Tools → MCP — no External Knowledge Base, no session-linking. The read is keyed by `product_id` + `user_id` only.

Wire the current user's stable id as a Dify input variable (`{{user_id}}`) referenced in the agent instructions, and pass it in `inputs.user_id` on every Dify API call — it must exactly equal the id your activity source identifies the user with. See the full tutorial for the MCP server setup and identity wiring.

## Reference

- Full tutorial: https://developers.autoplay.ai/recipes/dify-tutorial
