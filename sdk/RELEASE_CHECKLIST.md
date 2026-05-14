# SDK Feedback Remediation Release Checklist

## Release A (Patch: reliability + safety)

- [ ] Verify `ContextStore.get(...)` warns/falls back when `product_id` is missing and scoped buckets exist.
- [ ] Verify top-level exports include `agent_state_v2` and new helpers (`compose_chat_pipeline`, `UserSessionIndex`).
- [ ] Verify `__version__` resolves from package metadata.
- [ ] Verify `autoplay-install-skills` preserves existing directories by default and requires `--force` to overwrite.
- [ ] Run test suite:
  - `tests/test_sdk_context_store.py`
  - `tests/test_install_skills.py`
  - `tests/test_package_exports.py`

## Release B (Docs refresh)

- [ ] Quickstart includes:
  - PostHog key prefix guidance (`phc_` vs `phx_`)
  - `posthog.register({ email })` guidance for consistent `payload.email`
  - Webhook URL UI + source-field requirement note
  - No real secret/token values in examples
  - Identity plumbing callout across PostHog/widget/chatbot IDs
- [ ] Agent-state docs include v1/v2 decision matrix.
- [ ] Payload schema docs enumerate stream event types and handler mapping.
- [ ] README includes compatibility notes (pydantic v1/v2), token env var guidance, and product-scoped context retrieval guidance.

## Release C (Self-hosted feature foundations)

- [ ] `UserSessionIndex` API stable (`add`, `get_recent_sessions`, `get_user_activity`, `reset_user`).
- [ ] `compose_chat_pipeline` wiring validated (context + writer summary fanout).
- [ ] Optional `autoplay_sdk.serve` module works with `autoplay-sdk[serve]`.
- [ ] New docs page available: `docs/sdk/self-hosted-bridge.mdx`.
- [ ] Run test suite:
  - `tests/test_user_index.py`
  - `tests/test_chat_pipeline.py`
  - `tests/test_serve_fastapi.py`

## Regression and consistency checks

- [ ] Confirm all quickstart and README snippets compile conceptually against current exports.
- [ ] Confirm docs references match actual symbols in `autoplay_sdk/__init__.py`.
- [ ] Confirm no lints introduced in modified Python files.
- [ ] Confirm changelog/release notes call out behavior changes:
  - ContextStore missing `product_id` fallback/warnings
  - `autoplay-install-skills --force` overwrite behavior
  - New optional `serve` extra
