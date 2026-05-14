---
name: chatbot-landbot
description: >-
  Wires the Autoplay SDK into Landbot for real-time user context. Use when the
  user mentions Landbot or asks how to give their Landbot chatbot real-time
  context from Autoplay.
disable-model-invocation: true
---

# Chatbot — Landbot

> Read `autoplay-core` first for install, credentials, and the stream wiring pattern.

## ⚠️ Session scoping — critical

Landbot conversations have a conversation ID. You must link the browser Autoplay `session_id` to the Landbot conversation before context can be delivered — see `autoplay-core` for the `conv_map` + `on_session_linked` pattern.

Full tutorial coming soon. See the docs for current status.

## Reference

- Tutorial: https://developers.autoplay.ai/recipes/landbot
