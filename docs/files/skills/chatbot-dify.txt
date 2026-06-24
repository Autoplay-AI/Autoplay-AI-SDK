---
name: chatbot-dify
description: >-
  Wires the Autoplay SDK into Dify by writing real-time user activity to a Dify
  External Knowledge Base keyed by session_id. Use when the user mentions Dify,
  Dify knowledge base, External Knowledge API, or asks how to give their Dify
  agent real-time context.
disable-model-invocation: true
---

# Chatbot — Dify

> Read `autoplay-core` first for install, credentials, and the stream wiring pattern.

## ⚠️ Session scoping — critical

Dify retrieves context via an **External Knowledge ID**. That ID must match the key you used when storing events. Pick `session_id` or `email` and use it consistently — if they don't match, retrieval returns empty or the wrong user's data.

See the full tutorial for step-by-step setup including the External Knowledge API endpoint, retrieval handler, and proactive trigger scoping.

## Reference

- Full tutorial: https://developers.autoplay.ai/recipes/dify-tutorial
