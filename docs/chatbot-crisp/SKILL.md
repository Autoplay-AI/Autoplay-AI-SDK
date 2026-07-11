---
title: "Crisp Hugo skill"
sidebarTitle: "Crisp Hugo"
description: "Connects an existing Crisp Hugo AI agent to Autoplay live activity through the Autoplay MCP server. Covers adding the MCP server in Crisp, enabling get_live_user_activity, and passing the same stable user ID used by the activity source. Use when the customer already uses Crisp, Crisp AI, Hugo, or Crisp MCP integrations."
---

# AI Support Agent — Crisp AI

> Read `autoplay-core` first for install and credentials (`product_id`, `mcp_url`, `mcp_key`).

## Scoping pattern for Crisp

Hugo (Crisp's AI agent) pulls a user's live activity on demand via an **Autoplay MCP server** connected in the Crisp dashboard — no webhook, no session-linking, no `conv_map`. The read is keyed by `product_id` + `user_id` only.

Push the user's stable id into the Crisp session via `$crisp.push(["set", "session:data", [[["user_id", currentUser.id]]]])` after login — it must exactly equal the id your activity source identifies the user with. See the full tutorial for the MCP server setup, tool description, and identity wiring.

## Reference

- Tutorial: https://developers.autoplay.ai/recipes/crisp-ai
