---
name: chatbot-crisp
description: >-
  Wires the Autoplay SDK into Crisp AI for real-time user context. Use when the
  user mentions Crisp, Crisp AI, or asks how to give their Crisp chatbot
  real-time context from Autoplay.
disable-model-invocation: true
---

# Chatbot — Crisp AI

> Read `autoplay-core` first for install and credentials (`product_id`, `mcp_url`, `mcp_key`).

## Scoping pattern for Crisp

Hugo (Crisp's AI agent) pulls a user's live activity on demand via an **Autoplay MCP server** connected in the Crisp dashboard — no webhook, no session-linking, no `conv_map`. The read is keyed by `product_id` + `user_id` only.

Push the user's stable id into the Crisp session via `$crisp.push(["set", "session:data", [[["user_id", currentUser.id]]]])` after login — it must exactly equal the id your activity source identifies the user with. See the full tutorial for the MCP server setup, tool description, and identity wiring.

## Reference

- Tutorial: https://developers.autoplay.ai/recipes/crisp-ai
