---
name: chatbot-crisp
description: >-
  Wires the Autoplay SDK into Crisp AI for real-time user context. Use when the
  user mentions Crisp, Crisp AI, or asks how to give their Crisp chatbot
  real-time context from Autoplay.
disable-model-invocation: true
---

# Chatbot — Crisp AI

> Read `autoplay-core` first for install, credentials, and the stream wiring pattern.

## ⚠️ Session scoping — critical

Crisp conversations have a `session_id`. You must link the browser Autoplay `session_id` to the Crisp `conversation_id` before context can be delivered — see `autoplay-core` for the `conv_map` + `on_session_linked` pattern.

Full tutorial coming soon. See the docs for current status.

## Reference

- Tutorial: https://developers.autoplay.ai/recipes/crisp-ai
