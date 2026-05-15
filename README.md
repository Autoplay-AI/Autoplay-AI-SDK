<div align="center">

<img src="docs/images/logo-2.svg" alt="Autoplay" width="80" />

# autoplay-sdk

**Transform your existing customer support chatbot into a proactive, personalized experience for every user.**

[![PyPI](https://img.shields.io/pypi/v/autoplay-sdk)](https://pypi.org/project/autoplay-sdk)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://pypi.org/project/autoplay-sdk)
[![CI](https://github.com/Autoplay-AI/autoplay-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/Autoplay-AI/autoplay-sdk/actions/workflows/ci.yml)
[![Discord](https://img.shields.io/badge/Discord-join-5865F2?logo=discord&logoColor=white)](https://discord.gg/jCbR2tQA5)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[Documentation](https://developers.autoplay.ai) · [Quickstart](https://developers.autoplay.ai/quickstart) · [Discord](https://discord.gg/jCbR2tQA5) · [PyPI](https://pypi.org/project/autoplay-sdk)

</div>

---


**The problem with reactive customer support chatbots:**

- They wait to be asked — assuming users will speak up when they're stuck. They rarely do.

- And when users do ask, they're expected to know how to frame their question correctly. But users don't know what they don't know about your platform and often initiate the conversation in the wrong way.

**What we propose you build with our SDK:**

- Don't wait for users to come to your chatbot. Go to them first — with the right help framed in the right way, at the right moment, personalized to what they've been doing in your platform.

- And don't just tell them how to fix it. Show them — by triggering contextual visual guidance through smart tooltips or a browser agent (coming soon).

---

## How it works

You probably already have all the tools — you just need to orchestrate them correctly:

![Autoplay SDK architecture — session replay feeds into the Autoplay SDK processor, which drives your chatbot and visual guidance tools](docs/images/integrations-diagram.png)

---

## Features

| | What Autoplay handles for you |
|---|---|
| **Real-time events** | Browser activity becomes normalised, typed payloads your model can read — no noisy raw data |
| **Context tooling** | Buffers, summarisers, and typed models keep high event volume from blowing your context window |
| **Golden paths** | Record ideal product journeys so your agent always knows the optimal route through your product |
| **Workflow tracking** | Per-user mastery, in-progress steps, and gaps across sessions — so suggestions never repeat |
| **Proactive triggers** | Fire chat or visual nudges at exactly the right moment based on real-time activity |
| **Agent session states** | Built-in FSM that gates when your copilot speaks — never over-interrupts |

---

## Quick Start

**Requirements:** Python 3.10+

```bash
pip install autoplay-sdk
# or
uv add autoplay-sdk
```

**The fastest way to get set up is with the AI agent skills.** Once installed, you can open Cursor or Claude and just say *"Set up Autoplay with Intercom and PostHog"* — the agent handles the entire wiring process for you: connecting your event source, scoping sessions correctly, linking chat conversations to user activity, and dropping in the right context assembly pattern for your stack.

Run this once from your project root after installing:

```bash
autoplay-install-skills
# or target your specific stack:
autoplay-install-skills --chatbot intercom --user-activity posthog
autoplay-install-skills --chatbot ada --user-activity fullstory
```

This drops a `.cursor/skills/` folder into your project. From there, your AI assistant knows exactly what to build and in what order — no guessing, no reading docs, no getting the session scoping wrong.

**[→ Full setup guide on developers.autoplay.ai/quickstart](https://developers.autoplay.ai/quickstart)**

The quickstart walks through adding the PostHog frontend snippet, registering your product, and streaming your first live events in under 10 minutes.

---

## Chatbot tutorials

Step-by-step guides for wiring Autoplay into your existing chatbot platform.

| | Platform | Tutorial |
|---|---|---|
| <img src="docs/images/recipes/intercom/logo.png" width="24"> | Intercom | [View tutorial →](https://developers.autoplay.ai/recipes/intercom/how-to-setup) |
| <img src="docs/images/recipes/ada/logo.png" width="24"> | Ada | [View tutorial →](https://developers.autoplay.ai/recipes/ada/how-to-setup) |
| <img src="docs/images/recipes/botpress/logo.png" width="24"> | Botpress | [View tutorial →](https://developers.autoplay.ai/recipes/botpress/how-to-setup) |
| <img src="docs/images/recipes/dify/logo.png" width="24"> | Dify | [View tutorial →](https://developers.autoplay.ai/recipes/dify/how-to-setup) |
| <img src="docs/images/recipes/tidio/logo.png" width="24"> | Tidio | [View tutorial →](https://developers.autoplay.ai/recipes/tidio/how-to-setup) |
| <img src="docs/images/recipes/landbot/logo.png" width="24"> | Landbot | [View tutorial →](https://developers.autoplay.ai/recipes/landbot/how-to-setup) |
| <img src="docs/images/recipes/crisp/logo.png" width="24"> | Crisp AI | [View tutorial →](https://developers.autoplay.ai/recipes/crisp/how-to-setup) |
| | Rasa | Coming soon |
| | Inkeep | Coming soon |

---

## AI agent skills (Cursor / Claude)

The SDK ships with agent skills that teach your AI assistant exactly how to wire Autoplay for your stack:

```bash
autoplay-install-skills
# or target your specific stack:
autoplay-install-skills --chatbot intercom --user-activity posthog
autoplay-install-skills --chatbot ada --user-activity fullstory
```

This drops a `.cursor/skills/` folder into your project. Open Cursor or Claude and say *"Set up Autoplay with Intercom and PostHog"* — the agent follows the correct wiring pattern automatically.

---

## Community and contact

| | |
|---|---|
| **Discord** | [discord.gg/jCbR2tQA5](https://discord.gg/jCbR2tQA5) — share what you're building, get help, stay updated |
| **GitHub Issues** | Best for bug reports and feature requests |
| **Support policy** | See [SUPPORT.md](SUPPORT.md) for support channels and response expectations |
| **Docs** | [developers.autoplay.ai](https://developers.autoplay.ai) |
| **PyPI** | [pypi.org/project/autoplay-sdk](https://pypi.org/project/autoplay-sdk) |

---

## Project governance

- Contributor expectations: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- Security reporting policy: [SECURITY.md](SECURITY.md)
- Maintainer model and release governance: [GOVERNANCE.md](GOVERNANCE.md)
- Open-source maintainer checklist (GitHub settings): [.github/OPEN_SOURCE_MAINTAINER_CHECKLIST.md](.github/OPEN_SOURCE_MAINTAINER_CHECKLIST.md)

---

## License

MIT — see [LICENSE](LICENSE).
