---
name: chatbot-landbot
description: >-
  Wires the Autoplay SDK into Landbot for real-time user context. Use when the
  user mentions Landbot or asks how to give their Landbot chatbot real-time
  context from Autoplay.
disable-model-invocation: true
---

# Chatbot — Landbot

> Read `autoplay-core` first for install and credentials (`product_id`, `mcp_url`, `mcp_key`).

## Scoping pattern for Landbot

Landbot has no native MCP support, so a small backend route pulls a user's live activity on demand and returns it to a Landbot Webhook block — no session-linking, no `conv_map`, no listener process. The read is keyed by `product_id` + `user_id` only; thread the user's stable id into the Webhook URL as a query param (e.g. `?user_id=[@user_id]`) so your route can pass it straight through.

`user_id` must exactly equal the id your activity source identifies the user with. See the full tutorial for the Landbot workflow, the backend route, and identity wiring.

## Reference

- Tutorial: https://developers.autoplay.ai/recipes/landbot
