# SDK Feedback Triage Map

Source: `/Users/marieliesse/Downloads/DOCS_FEEDBACK.md` (May 2026)

| # | Item | Priority | Type | Target files | Suggested owner |
|---|---|---|---|---|---|
| 1 | PostHog `phc_` vs `phx_` key prefix warning | P0 | docs | `docs/quickstart.mdx` | Docs |
| 2 | `payload.email` stays `None` without `posthog.register` | P0 | docs | `docs/quickstart.mdx` | Docs |
| 3 | PostHog Webhook URL field required in UI and source | P0 | docs | `docs/quickstart.mdx` | Docs |
| 4 | Hog script placeholder/manual substitution risk | P1 | docs | `docs/quickstart.mdx`, `autoplay_sdk/admin/onboard.py`, `autoplay_sdk/admin/product_onboarding.py` | Docs + SDK |
| 5 | v1 vs v2 agent-state decision matrix | P0 | docs | `docs/sdk/agent-states.mdx` | Docs |
| 6 | `agent_state_v2` not discoverable from top-level package | P0 | docs + code | `autoplay_sdk/__init__.py`, `README.md` | SDK |
| 7 | `ContextStore.get()` silent empty without `product_id` | P0 | bug | `autoplay_sdk/context_store.py`, `README.md`, `tests/test_sdk_context_store.py` | SDK |
| 8 | `BaseChatbotWriter` framing sounds vendor-only | P1 | docs | `docs/sdk/chatbot-writer.mdx` | Docs |
| 9 | `enrich` vs `assemble_rag_chat_context` unclear | P1 | docs | `README.md`, `docs/sdk/chatbot-context-assembly.mdx` | Docs |
| 10 | Identity plumbing across PostHog/widget/chatbot IDs | P1 | docs | `docs/quickstart.mdx`, `autoplay_sdk/skills/autoplay-core/SKILL.md` | Docs |
| 11 | pydantic v1 compatibility not documented | P1 | docs | `README.md` | SDK + Docs |
| 12 | `product_id` in `identify` snippet is Autoplay-specific | P1 | docs | `docs/quickstart.mdx` | Docs |
| 13 | SSE event types not enumerated | P1 | docs | `docs/sdk/payload-schema.mdx`, `README.md` | Docs |
| 14 | `__version__` mismatch with package version | P0 | bug | `autoplay_sdk/__init__.py` | SDK |
| 15 | `autoplay-install-skills` deletes dirs without confirmation | P0 | bug | `autoplay_sdk/install_skills.py`, `tests/test_install_skills.py` | SDK |
| 16 | `autoplay-core` skill documents non-existent `call_llm` | P1 | docs + bug | `autoplay_sdk/skills/autoplay-core/SKILL.md` | SDK |
| 17 | `onboard_product(contact_email=...)` requirement visibility | P1 | docs | `docs/quickstart.mdx`, `README.md` | Docs |
| 18 | Quickstart Step 5 output framing mismatch | P2 | docs | `docs/quickstart.mdx` | Docs |
| 19 | `AUTOPLAY_APP_UNKEY_TOKEN` env var undocumented | P1 | docs | `README.md`, `docs/quickstart.mdx` | Docs |
| 20 | "Two RAG surfaces" section appears too early and unprimed | P2 | docs | `README.md` | Docs |
| 21 | Feature: `UserSessionIndex` primitive | P2 | feature | `autoplay_sdk/user_index.py`, `autoplay_sdk/__init__.py`, `tests/test_user_index.py`, `README.md` | SDK |
| 22 | Feature: `autoplay_sdk.serve` FastAPI helper | P2 | feature | `autoplay_sdk/serve/fastapi.py`, `autoplay_sdk/serve/__init__.py`, `pyproject.toml`, `README.md` | SDK |

## Delivery order

1. P0 reliability and safety (`#7`, `#14`, `#15`, `#6` code portion).
2. P0/P1 docs and discoverability (`#1`, `#2`, `#3`, `#5`, plus remaining docs items).
3. P2 feature foundations (`#21`, `#22`) and docs updates.
