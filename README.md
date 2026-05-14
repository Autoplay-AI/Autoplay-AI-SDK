<div align="center">

<img src="docs/images/logo-2.svg" alt="Autoplay" width="80" />

# autoplay-sdk

**Give your AI copilot real-time eyes inside your product.**

[![PyPI](https://img.shields.io/pypi/v/autoplay-sdk)](https://pypi.org/project/autoplay-sdk)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://pypi.org/project/autoplay-sdk)
[![Discord](https://img.shields.io/badge/Discord-join-5865F2?logo=discord&logoColor=white)](https://discord.gg/jCbR2tQA5)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[Documentation](https://developers.autoplay.ai) · [Quickstart](https://developers.autoplay.ai/quickstart) · [Discord](https://discord.gg/jCbR2tQA5) · [PyPI](https://pypi.org/project/autoplay-sdk)

</div>

---

## What is Autoplay?

Most customer support copilots are blind. They don't know a user just spent 10 minutes stuck on the same screen, that they've never completed onboarding, or that they're one click away from churning. They wait to be asked. **And by then, it's too late.**

**Autoplay streams everything users are doing inside your product — in real time — directly into your AI agent as clean, LLM-ready context.** Your copilot sees what they're clicking, where they're stuck, and what they've mastered, so it can help before someone asks, guide them to the next right step, and stay quiet when it shouldn't interrupt.

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

Stream live user events into your chatbot handler in a few lines:

```python
from autoplay_sdk import AsyncConnectorClient

STREAM_URL = "https://your-connector.onrender.com/stream/YOUR_PRODUCT_ID"
API_TOKEN  = "unkey_xxxx..."

async def on_actions(payload):
    print(payload.to_text())  # LLM-ready context string

async with AsyncConnectorClient(url=STREAM_URL, token=API_TOKEN) as client:
    client.on_actions(on_actions)
    await client.run()
```

**Enrich a user query with their live session context before hitting your vector DB:**

```python
from autoplay_sdk.context_store import AsyncContextStore

context_store = AsyncContextStore(lookback_seconds=300, max_actions=20)
client.on_actions(context_store.add)

# In your chatbot handler:
enriched = context_store.enrich(session_id, user_message)
results  = await vector_db.query(await embed(enriched))
```

---

## How it works

```
Your frontend (PostHog snippet)
        ↓
Autoplay event connector   ← normalises, batches, and summarises UI events
        ↓
autoplay-sdk (SSE stream)  ← typed ActionsPayload / SummaryPayload
        ↓
Your AI agent              ← real-time context injected into every inference call
```

---

## Full setup guide

The three-step setup (Autoplay app → frontend snippet → SDK registration) is covered in the full docs:

**[→ Quickstart on developers.autoplay.ai](https://developers.autoplay.ai/quickstart)**

Want to wire Autoplay into a specific chatbot platform? We have step-by-step tutorials for:

- [Intercom](https://developers.autoplay.ai/recipes/intercom-tutorial/step-1-connect-real-time-events)
- [Ada](https://developers.autoplay.ai/recipes/ada/step-1-connect-real-time-events)
- [Botpress](https://developers.autoplay.ai/recipes/botpress/step-1-connect-real-time-events)
- [Tidio, Landbot, Dify, Crisp AI](https://developers.autoplay.ai)

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
| **Docs** | [developers.autoplay.ai](https://developers.autoplay.ai) |
| **PyPI** | [pypi.org/project/autoplay-sdk](https://pypi.org/project/autoplay-sdk) |

---

## License

MIT — see [LICENSE](LICENSE).
