---
title: "Chatbot Dify"
sidebarTitle: "Chatbot Dify"
description: "Wires the Autoplay SDK into Dify for real-time user context. Use when the user mentions Dify or asks how to give their Dify agent real-time context from Autoplay."
---

# Chatbot — Dify

> Read `autoplay-core` first for install and credentials (`product_id`, `mcp_url`, `mcp_key`).

## Scoping pattern for Dify

The Dify Agent pulls a user's live activity on demand via an **Autoplay MCP server** added under Tools → MCP — no External Knowledge Base, no session-linking. The read is keyed by `product_id` + `user_id` only.

Wire the current user's stable id as a Dify input variable (`{{user_id}}`) referenced in the agent instructions, and pass it in `inputs.user_id` on every Dify API call — it must exactly equal the id your activity source identifies the user with. See the full tutorial for the MCP server setup and identity wiring.

## Reference

- Full tutorial: https://developers.autoplay.ai/recipes/dify-tutorial
