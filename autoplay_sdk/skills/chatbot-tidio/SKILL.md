---
name: chatbot-tidio
description: >-
  Wires the Autoplay SDK into Tidio for real-time user context. Use when the
  user mentions Tidio or asks how to give their Tidio chatbot real-time
  context from Autoplay.
disable-model-invocation: true
---

# Chatbot — Tidio

> Read `autoplay-core` first for install, credentials, and the stream wiring pattern.

## ⚠️ Session scoping — critical

Tidio conversations have a conversation ID. You must link the browser Autoplay `session_id` to the Tidio conversation before context can be delivered — see `autoplay-core` for the `conv_map` + `on_session_linked` pattern.

Full tutorial coming soon. See the docs for current status.

## Reference

- Tutorial: https://developers.autoplay.ai/recipes/tidio
