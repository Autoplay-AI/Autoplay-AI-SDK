<div align="center">

<img src="docs/images/logo-2.svg" alt="Autoplay" width="80" />

# autoplay-sdk

**Transform your existing customer support chatbot into a proactive, personalized experience for every user.**

[![PyPI](https://img.shields.io/pypi/v/autoplay-sdk)](https://pypi.org/project/autoplay-sdk)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://pypi.org/project/autoplay-sdk)
[![CI](https://github.com/Autoplay-AI/Autoplay-proactive-visual-customer-support/actions/workflows/ci.yml/badge.svg)](https://github.com/Autoplay-AI/Autoplay-proactive-visual-customer-support/actions/workflows/ci.yml)
[![Discord](https://img.shields.io/badge/Discord-join-5865F2?logo=discord&logoColor=white)](https://discord.gg/jCbR2tQA5)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[Documentation](https://developers.autoplay.ai) · [Quickstart](https://developers.autoplay.ai/quickstart) · [Discord](https://discord.gg/jCbR2tQA5) · [PyPI](https://pypi.org/project/autoplay-sdk)

</div>

---

## 🤔 The problem

**The problem with reactive customer support chatbots:**

- They wait to be asked — assuming users will speak up when they're stuck. They rarely do.
- When users do ask, they're expected to know how to frame their question correctly. But users don't know what they don't know about your platform, and often initiate the conversation in the wrong way.

**What we propose you build with our SDK:**

- Don't wait for users to come to your chatbot. Go to them first — with the right help, at the right moment, personalized to what they've been doing in your platform.
- Don't just tell them how to fix it. Show them — by triggering contextual visual guidance through smart tooltips or a browser agent (coming soon).

---

## ⚙️ How it works

You have all the tools in your tech stack — you just need to orchestrate them correctly:
1) session replay provider
2) chatbot provider
3) visual guidance provider

![Autoplay SDK architecture — session replay feeds into the Autoplay SDK processor, which drives your chatbot and visual guidance tools](docs/images/integrations-diagram.png)

---

## ✨ Features

| Feature | What it does |
|---|---|
| **Real-time event stream** | Captures and normalizes browser activity into clean, structured data your model can actually use |
| **Context management** | Automatically buffers and summarizes high-volume events so you never blow your context window |
| **Golden paths** | Record your product's ideal user journeys once — your agent always guides users the right way |
| **Per-user memory** | Tracks what each user knows, where they got stuck, and what they've done — so your agent never repeats itself |
| **Proactive triggers** | Detects the right moment to intervene and fires a chat message or visual nudge automatically |
| **Interruption control** | A built-in state machine ensures your copilot only speaks when it should — helpful, never annoying |

---

## 🚀 Quick Start

**Requirements:** Python 3.10+

```bash
pip install autoplay-sdk
# or
uv add autoplay-sdk
```

**The fastest way to get set up is with the AI agent skills.** Run this once from your project root after installing:

```bash
autoplay-install-skills
# or target your specific stack:
autoplay-install-skills --chatbot intercom --user-activity posthog
autoplay-install-skills --chatbot ada --user-activity fullstory
```

This drops a `.cursor/skills/` folder into your project. Then open Cursor or Claude and say *"Set up Autoplay with Intercom and PostHog"* — the agent handles the full wiring automatically: session scoping, conversation linking, and context assembly for your stack.

**[→ Full setup guide on developers.autoplay.ai/quickstart](https://developers.autoplay.ai/quickstart)**

The quickstart covers the PostHog frontend snippet, product registration, and streaming your first live events in under 10 minutes.

---

## 🤖 Chatbot tutorials

Step-by-step guides for wiring Autoplay into your existing chatbot platform.

| | Platform | Tutorial |
|---|---|---|
| <img src="docs/images/recipes/intercom/logo.png" width="24"> | Intercom | [View tutorial →](https://developers.autoplay.ai/recipes/intercom-tutorial/step-1-connect-real-time-events) |
| <img src="docs/images/recipes/ada/logo.png" width="24"> | Ada | [View tutorial →](https://developers.autoplay.ai/recipes/ada/step-1-connect-real-time-events) |
| <img src="docs/images/recipes/botpress/logo.png" width="24"> | Botpress | [View tutorial →](https://developers.autoplay.ai/recipes/botpress/step-1-connect-real-time-events) |
| <img src="docs/images/recipes/dify/logo.png" width="24"> | Dify | [View tutorial →](https://developers.autoplay.ai/recipes/dify-tutorial) |
| <img src="docs/images/recipes/tidio/logo.png" width="24"> | Tidio | [View tutorial →](https://developers.autoplay.ai/recipes/tidio/step-1-connect-real-time-events) |
| <img src="docs/images/recipes/landbot/logo.png" width="24"> | Landbot | [View tutorial →](https://developers.autoplay.ai/recipes/landbot/step-1-connect-real-time-events) |
| <img src="docs/images/recipes/crisp/logo.png" width="24"> | Crisp AI | [View tutorial →](https://developers.autoplay.ai/recipes/crisp-ai) |
| <img src="docs/images/recipes/rasa/logo.png" width="24"> | Rasa | Coming soon |
| <img src="docs/images/recipes/inkeep/logo.png" width="24"> | Inkeep | Coming soon |

---

## 💬 Community

| | |
|---|---|
| **Discord** | [discord.gg/jCbR2tQA5](https://discord.gg/jCbR2tQA5) — share what you're building, get help, stay updated |
| **GitHub Issues** | Best for bug reports and feature requests |
| **Support** | See [SUPPORT.md](SUPPORT.md) for channels and response expectations |
| **Docs** | [developers.autoplay.ai](https://developers.autoplay.ai) |
| **PyPI** | [pypi.org/project/autoplay-sdk](https://pypi.org/project/autoplay-sdk) |

---

## 📋 Contributing

- Contributor guide: [CONTRIBUTING.md](CONTRIBUTING.md)
- Code of conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- Security reporting: [SECURITY.md](SECURITY.md)

---

## 📄 License

MIT — see [LICENSE](LICENSE).

