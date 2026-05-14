# Changelog

All notable changes to `autoplay_sdk` are documented here.

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) style: **Added** / **Changed** / **Deprecated** / **Removed** / **Fixed** / **Security** where applicable, plus **Documentation** for user-facing doc-only updates.

---

## [0.7.2] — 2026-05-14

### Removed

- **`TourDefinition.label`** and **`TourDefinition.user_tour_exists`** — these fields belong to `proactive_intercom.messages`, not the tour registry. Removed from the dataclass, `to_dict`, and `from_dict`. Legacy configs that still include these keys are silently ignored on parse so existing deployments do not break.

### Added

- **`TOUR_OFFER_QUICK_REPLY_BODY`** — constant in `autoplay_sdk.proactive_triggers` (`"Would you like me to show you?"`). Default body text for the tour-offer Yes/No quick reply sent after the LLM reply.
- **`tour_offer_quick_reply_body(integration_config)`** — helper in `autoplay_sdk.proactive_triggers`; returns the body for the tour-offer message. Reads `integration_config.tour_offer_body` so each product can override the wording; falls back to `TOUR_OFFER_QUICK_REPLY_BODY` when the key is absent or blank. Call this after the LLM reply whenever `resolve_tour_offer_for_inbound` returns a non-`None` flow id. Both symbols are exported from `autoplay_sdk.proactive_triggers.__all__`.

---

## [0.7.1] — 2026-05-13

### Added

- **`autoplay_sdk.install_skills`** — CLI command `autoplay-install-skills` that copies bundled Cursor/Claude agent skills into the current project's `.cursor/skills/` directory. Supports `--chatbot <name>` and `--user-activity <name>` flags to install only the relevant skills for a given stack. Always installs `autoplay-core`.
- **`autoplay_sdk/skills/`** — 10 agent skill files shipped inside the wheel: `autoplay-core` (universal SDK setup, session scoping, conversation scoping guardrails), `chatbot-ada`, `chatbot-intercom`, `chatbot-botpress`, `chatbot-dify`, `chatbot-crisp`, `chatbot-landbot`, `chatbot-tidio`, `activity-fullstory`, `activity-posthog`.

### Documentation

- [`docs/recipes/ada/step-1-connect-real-time-events.mdx`](docs/recipes/ada/step-1-connect-real-time-events.mdx) — full Ada tutorial: `metaFields` injection pattern, Ada Variables setup, FastAPI context endpoint, Web SDK integration, and Ada events reference.
- [`docs/recipes/ada/`](docs/recipes/ada/) — new Ada tutorial section added under Chatbot Tutorials.
- [`docs/recipes/fullstory/how-to-setup.mdx`](docs/recipes/fullstory/how-to-setup.mdx) — full FullStory Streams tutorial: creating a Stream, JSON field mapping, IP allowlist, verification steps.
- [`docs/quickstart.mdx`](docs/quickstart.mdx) — added `autoplay-install-skills` tip block after the `pip install` step and two new Cards in the next-steps section.

---

## [0.7.0] — 2026-05-12

### Added

- **`autoplay_sdk.agent_state_v2`** — new `SessionState` FSM with three states (`THINKING`, `PROACTIVE`, `REACTIVE`), strict timeout-only exit rules from active states, and `InvalidTransitionError` (separate from v1). Coexists with `AgentStateMachine` (v1); nothing in v1 was removed.
- **`autoplay_sdk.proactive_triggers.trigger_config`** — `ProactiveTriggerConfig`, `TriggerMessage`, and recursive `ProactiveCriteria` (leaf `{id, name, type}` or group `{id, name, operator, conditions[]}`) for config-driven proactive trigger definitions.
- **`autoplay_sdk.proactive_triggers.tour_registry`** — `TourDefinition` and `TourRegistry` for per-tour `interaction_timeout_s` and `cooldown_period_s` overrides. Registry is product-scoped and keyed by `user_tour_id` (Intercom flow ID) via `get_by_user_tour_id()`.
- **`SessionState.record_tour_step()`** — records any tour progress (page advance, step complete) as an interaction, resetting `last_interaction_at` even when the user has never opened the chat.
- **`SessionState.set_visual_guidance(active, tour_id=None)`** — sets `visual_guidance_active` and `active_tour_id` on the session; raises `InvalidTransitionError` if called from `THINKING`.
- **`SessionState.tick(tour_registry=None)`** — resolves per-tour `interaction_timeout_s` and `cooldown_period_s` from the registry when `active_tour_id` is set; falls back to session defaults otherwise.
- **`parse_tour_registry(integration_config, product_id)`** — helper in `proactive_intercom_config` to parse `integration_config["tour_registry"]` into a `TourRegistry`.

### Changed

- **`integration_config.proactive_intercom`** — now a **list** of `ProactiveTriggerConfig` objects (was a single dict). Each entry has `id`, `name`, `proactive_criteria`, and `messages` (1–3 `TriggerMessage` objects). Session-level `interaction_timeout_s` and `cooldown_period_s` moved to top-level `integration_config`.
- **`integration_config.tour_registry`** — new top-level key (separate from `proactive_intercom`) for visual guidance tour definitions.
- **`TriggerMessage`** — renamed `offers_tour` → `user_tour_exists`, `flow_id` → `user_tour_id` (backward-compatible properties retained for existing configs).

### Documentation

- [`docs/recipes/intercom-tutorial/step-2-define-proactive-triggers.mdx`](docs/recipes/intercom-tutorial/step-2-define-proactive-triggers.mdx) — fully written; covers agent state v2 (why states are needed, state diagram, plain-English state descriptions), proactive trigger config (criteria leaf/group, chip messages), and tour registry (per-tour timeouts, `record_tour_step` lifecycle).
- [`docs/sdk/agent-states.mdx`](docs/sdk/agent-states.mdx) — added agent state v2 accordion with states, transition rules, session-level timeout settings, per-state sub-dataclasses, key methods, and persistence.

---

## [0.6.9] — 2026-05-12

### Added

- **`AgentStateMachine.enter_reactive_from_user_message`** — moves to **`reactive_assistance`** for inbound typed chat (no-op if already reactive; otherwise uses FSM validation via **`transition_to`**, logs transition rejections, and re-raises **`InvalidTransitionError`**). Used by the Intercom inbound handler when **`proactive_assistance`** text does not match the proactive chip so RAG can run.

- **`autoplay_sdk.proactive_triggers.context_source`** — **`RecentActionsPayloadSource`** (protocol) and **`build_proactive_context_from_payloads`** as a thin wrapper over **`ProactiveTriggerContext.from_actions_payloads`** for hosts that load **`ActionsPayload`** batches from pluggable sources.
- **`autoplay_sdk.proactive_triggers.section_activity`** — **`build_product_section_playbook`**, **`resolve_section_id`**, **`top_playbook_section_id`**, **`resolve_section_id_for_playbook`** for **`context_extra.product_section_playbook`** (per-section **`dwell_seconds_per_visit`**, visits, timestamps from **`canonical_url`** + **`section_url_rules`**).
- **`SectionPlaybookTrigger`** — resolves **`section_playbook`** rows using **`product_section_playbook`** metrics + precedence (**`current_section_id`** override, ranked dwell, **`runtime.current_section_id`**).

### Changed

- **Event connector** — default ``proactive_triggers.mode`` is now ``default_registry`` for all products (including the Autoplay connector id). New SDK built-ins in the registry are evaluated without an extra id filter unless the product sets ``mode: ping_pong_only``. See ``event_connector.integrations.proactive.proactive_trigger_mode`` and ``trigger_evaluation.py``.

- **`autoplay_sdk.proactive_triggers.builtin_catalog`** — **`BuiltinTriggerCatalogEntry`** and host **`integration_config.proactive_triggers.builtins`** rows **require** string fields **`id`**, **`name`**, and **`description`** (non-empty after strip). **`list_builtin_trigger_catalog()`** includes **`description`**. **`ResolvedBuiltinTriggerSpec`** includes **`description`**. **`registry_from_builtin_specs`** / **`resolve_builtin_specs`** raise **`SdkConfigError`** on missing, empty, or non-string values (each failure also logs **ERROR** with **`event=proactive_builtin_spec_invalid`**). **`default_proactive_trigger_registry()`** supplies **`name`** / **`description`** from the catalog entry.

### Documentation

- [`docs/sdk/proactive-triggers-authoring.mdx`](docs/sdk/proactive-triggers-authoring.mdx) — how to build a new trigger (custom, catalog, or JSON); **default values** for timings, context lookback/cap, and `integration_config.proactive_triggers` rows; **required** **`id` / `name` / `description`** on catalog entries and **`builtins`** JSON.
- [`docs/sdk/proactive-triggers.mdx`](docs/sdk/proactive-triggers.mdx) — short defaults summary and link to authoring.
- [`autoplay_sdk/proactive_triggers/README.md`](autoplay_sdk/proactive_triggers/README.md) — build paths, defaults table, and required string fields.
- [`event_connector/integrations/README.md`](../event_connector/integrations/README.md) — building new triggers via SDK vs JSON; **`builtins`** row shape (**`id`**, **`name`**, **`description`**) and timing defaults.

---

## [0.6.8] — 2026-05-05

### Added

- **`autoplay_sdk.agent_states.AgentStateMachine.enter_reactive_from_user_message`** now emits an explicit warning log with FSM context before re-raising **`InvalidTransitionError`** on illegal transitions.

### Documentation

- [`docs/sdk/agent-states.mdx`](docs/sdk/agent-states.mdx) — clarified `enter_reactive_from_user_message` behavior and rejection logging semantics.
- [`docs/changelog.mdx`](docs/changelog.mdx) — added 0.6.8 release entry for branch cut tracking.

---

## [0.6.7] — 2026-04-30

Single release bundling agent FSM, Intercom proactive **`quick_reply`**, the **`proactive_triggers`** package (replacing **`integrations.proactive`**), registry timings/entity, context builders, scope validation, product-scoped context-store buckets, and proactive **idle teardown** for chat integrations (**`run_proactive_idle_expiry`**) with host hooks, **`ProactiveIdleExpiryResult`**, and Intercom **`DELETE /conversations/{id}`** helpers.

### Removed

- **`autoplay_sdk.integrations.proactive`** — proactive detection lives in **`autoplay_sdk.proactive_triggers`**. **Migration:** replace `from autoplay_sdk.integrations.proactive import …` with `from autoplay_sdk.proactive_triggers import …`, and `…integrations.proactive.defaults` / `…proactive.types` with `…proactive_triggers.defaults`, `…proactive_triggers.types`, etc.

### Added

- **`autoplay_sdk.agent_states`** — **`AgentState`** (`StrEnum`), **`AgentStateMachine`**, **`TaskProgress`**, **`SessionMetrics`**, **`InvalidTransitionError`**, **`InvalidSnapshotError`**. Five-state FSM: **`thinking`**, **`reactive_assistance`**, **`proactive_assistance`**, **`guidance_execution`**, **`conservative_assistance`**; **`transition_on_disengagement()`** from **`guidance_execution`** → **`conservative_assistance`**; **`to_snapshot()`** / **`from_snapshot()`** (`_v` = 1); **`can_show_proactive_with_reason()`**.
- **`autoplay_sdk.agent_states.AgentStateMachine`** — **`expire_proactive_to_thinking_if_idle(now, interaction_timeout_s)`** to leave **`proactive_assistance`** when the offer idles past **`interaction_timeout_s`**.
- **`autoplay_sdk.integrations.intercom`** — proactive Messenger **`quick_reply`** helpers: **`INTERCOM_API_VERSION_QUICK_REPLY`** (`Unstable`), **`intercom_quick_reply_http_headers`**, **`build_intercom_quick_reply_reply_payload`**, **`normalize_intercom_quick_reply_labels`**, **`INTERCOM_PROACTIVE_QUICK_REPLY_DEFAULT_BODY`**, **`proactive_trigger_canonical_url_ping_pong`**, optional connector LLM-label URL/body builders (**`intercom_connector_llm_prompt_labels_url`**, **`build_connector_llm_prompt_labels_request_body`**), **`IntercomProactivePolicyConfig`**.
- **`autoplay_sdk.proactive_triggers`** — **`ProactiveTriggerContext`**, **`ProactiveTriggerResult`**, **`ProactiveTrigger`** protocol, **`ProactiveTriggerRegistry`** (**`evaluate_first`**, **`evaluate_all`**), **`CanonicalPingPongTrigger`**, **`default_proactive_trigger_registry`**, **`TRIGGER_ID_CANONICAL_URL_PING_PONG`**; **`ProactiveTriggerTimings`**, **`ProactiveTriggerEntity`**, **`ProactiveTriggerResult.interaction_timeout_s`** / **`cooldown_s`** (defaults **10s** / **30s** with **`DEFAULT_INTERACTION_TIMEOUT_S`** / **`DEFAULT_COOLDOWN_S`**). **`default_proactive_trigger_registry()`** wraps **`CanonicalPingPongTrigger`** with **`ProactiveTriggerEntity`** and default timings.
- **`autoplay_sdk.proactive_triggers.defaults`** — **`ProactiveTriggerIds`**, **`get_proactive_trigger_ids()`**, **`DEFAULT_PROACTIVE_QUICK_REPLY_BODY`**; stable **`trigger_id`** strings for built-in triggers.
- **`autoplay_sdk.proactive_triggers.PredicateProactiveTrigger`** — boolean-predicate helper for custom triggers without subclassing the protocol.
- **`ProactiveTriggerContext.from_actions_payloads`** — shared lookback + max-actions flattening aligned with :class:`~autoplay_sdk.context_store.AsyncContextStore` (defaults: 120s, 50 actions).
- **`ProactiveTriggerContext.from_slim_actions`** — build context from an already-windowed sequence of :class:`~autoplay_sdk.models.SlimAction`.
- **`DEFAULT_PROACTIVE_CONTEXT_LOOKBACK_S`**, **`DEFAULT_PROACTIVE_CONTEXT_MAX_ACTIONS`** — exported from :mod:`autoplay_sdk.proactive_triggers`.
- **`autoplay_sdk.proactive_triggers.scope`** — **`ScopePolicy`**, **`ProactiveScope`**, **`log_scope_violation`**, **`SCOPE_INVALID_EVENT`** for **`product_id`** / **`session_id`** validation on context factories.
- **`ProactiveTriggerContext.validate_scope`** — optional **`require_conversation`** for chat-linked surfaces.
- **`autoplay_sdk.context_store`** — **`actions_bucket_id`** and optional **`product_id`** on **`get`**, **`enrich`**, **`reset`**; **`add`** scopes **`_actions`** by **`(product_id, session_id)`** when **`ActionsPayload.product_id`** is set.
- **`autoplay_sdk.agent_states.types`** — **`ProactiveIdleExpiryResult`** (frozen dataclass; **`__bool__`** reflects **`transitioned`**; **`reset_chat_thread_binding`** when transitioning via idle expiry).
- **`autoplay_sdk.proactive_resilience`** — **`ProactiveResilienceKeySpace`**, **`proactive_key_suffixes`**, **`DEFAULT_MIN_INTERVAL_SECONDS`** (**300**); **`CircuitBreakerConfig`**, **`ProactiveRateLimitConfig`**, **`ProactiveResilienceConfig`**; **`ProactiveDeliveryOutcome`**, **`outcome_counts_toward_circuit`**; **`InMemoryProactiveCircuitBreaker`** for tests; **`ProactiveResilienceStore`** (**`Protocol`**). Hosts (event connector) persist via Redis; SDK stays Redis-free.
- **`autoplay_sdk.proactive_triggers.builtin_catalog`** — **`BuiltinTriggerCatalogEntry`**, **`BUILTIN_TRIGGER_CATALOG`**, **`ResolvedBuiltinTriggerSpec`**, **`list_builtin_trigger_catalog`**, **`resolve_builtin_specs`**, **`registry_from_builtin_specs`**; **`default_proactive_trigger_registry()`** implemented via **`registry_from_builtin_specs([{"id": "canonical_url_ping_pong"}])`**. Event connector **`integration_config.proactive_triggers.builtins`** selects ordered built-ins and optional **`interaction_timeout_s`** / **`cooldown_s`** overrides.
- **`autoplay_sdk.agent_states`** — **`proactive_idle_eligible(sm, now, interaction_timeout_s)`**; **`run_proactive_idle_expiry`**, **`ProactiveIdleExpiryHooks`** (**`Protocol`**), **`ProactiveIdleExpiryPipelineStatus`**, **`ProactiveIdleExpiryPipelineResult`** — ordered pipeline: eligible → **`await hooks.delete_remote_chat_thread()`** (**`True`** = success) → **`expire_proactive_to_thinking_if_idle`** → **`await hooks.clear_local_chat_thread_state()`**.
- **`autoplay_sdk.integrations.intercom`** — **`INTERCOM_API_VERSION_DELETE_CONVERSATION`**, **`intercom_delete_conversation_url`**, **`intercom_delete_conversation_headers`**, **`build_intercom_delete_conversation_request`** for **`DELETE {INTERCOM_REST_API_BASE}/conversations/{id}`** (optional **`retain_metrics`** query).

### Changed

- **`AgentStateMachine.expire_proactive_to_thinking_if_idle`** — returns **`ProactiveIdleExpiryResult`** instead of **`bool`**; truthiness preserved via **`ProactiveIdleExpiryResult.__bool__`**.
- **`autoplay_sdk.integrations.intercom`** — **`INTERCOM_PROACTIVE_QUICK_REPLY_DEFAULT_BODY`** aliases **`DEFAULT_PROACTIVE_QUICK_REPLY_BODY`** from **`autoplay_sdk.proactive_triggers.defaults`**.
- **`ProactiveTriggerContext`** — optional **`recent_actions`**, **`latest_summary_text`**, **`prior_session_summaries`**, **`context_extra`** (backward compatible defaults).
- **`ProactiveTriggerContext.from_slim_actions` / `from_actions_payloads`** — default **`scope_policy=ScopePolicy.STRICT`** (non-empty **`product_id`** and **`session_id`**). Pass **`ScopePolicy.LENIENT`** to skip validation.
- Connector-facing behaviour/docs: **`POST /intercom/proactive/{product_id}`** (LLM quick-reply labels) is always available when authenticated; the **`ENABLE_INTERCOM_PROACTIVE_PROMPTS`** env gate has been removed from the connector.

### Documentation

- [`docs/sdk/agent-states.mdx`](docs/sdk/agent-states.mdx) — FSM overview; **`expire_proactive_to_thinking_if_idle`**; **`proactive_idle_eligible`**, **`ProactiveIdleExpiryResult`**, **`run_proactive_idle_expiry`** / hooks; **Proactive idle expiry (chat integrations)** subsection.
- [`docs/integrations/intercom.mdx`](docs/integrations/intercom.mdx) — proactive quick replies, connector endpoint, timings, entity, idle expiry, stable **`trigger_id`** registry; gate + **`run_proactive_idle_expiry`** for idle teardown; delete-conversation helpers.
- [`docs/sdk/proactive-triggers.mdx`](docs/sdk/proactive-triggers.mdx) — **`autoplay_sdk.proactive_triggers`** overview.
- [`docs/sdk/proactive-triggers-authoring.mdx`](docs/sdk/proactive-triggers-authoring.mdx) — cookbook: context from actions/summaries, registry, ping-pong template, stable IDs; pair **`interaction_timeout_s`** with **`run_proactive_idle_expiry`** (chat) or **`expire_proactive_to_thinking_if_idle`** (FSM-only ticks).

### Breaking changes

- **`expire_proactive_to_thinking_if_idle`** return type is **`ProactiveIdleExpiryResult`**, not **`bool`**. **`if sm.expire_...():`** and **`bool(result)`** behave as before; **`is True` / `is False`** on the return value will not match — use **`result.transitioned`** or truthiness.
- **Import path:** migrate off **`autoplay_sdk.integrations.proactive`** to **`autoplay_sdk.proactive_triggers`** (see **Removed**).
- **Strict scope defaults:** **`from_slim_actions` / `from_actions_payloads`** default to **`ScopePolicy.STRICT`**; use **`ScopePolicy.LENIENT`** for permissive behaviour.
- **Context store keys:** when **`ActionsPayload.product_id`** is set on ingest, pass the same **`product_id`** into **`get` / `enrich` / `reset`** or reads use the legacy session-only bucket.

---

## [0.6.6] — 2026-04-23

### Added

- **`SlimAction`** — optional **`conversation_id`** (Intercom thread id when the PostHog session is linked).
- **`ActionsPayload`** — optional **`conversation_id`** at batch level (same semantics); **`merge`** picks the first non-null across merged payloads.
- **`autoplay_sdk.rag_query`** — query-time RAG assembly: **`assemble_rag_chat_context`**, **`RagChatProviders`**, **`ChatMemoryProvider`**, **`KnowledgeBaseRetriever`**, **`ChatContextAssembly`**, prompt formatters (**`format_rag_system_prompt`**, etc.). Designed around **user query**, **real-time context**, and **conversation history**; KB and memory backends are **pluggable**.
- **`autoplay_sdk.prompts`** — versioned **Adoption Copilot** defaults: **`RAG_SYSTEM_PROMPT`**, **`REASONING_PROMPT`**, **`RESPONSE_PROMPT`** (`name` / `description` / `version` / `content`).
- **`autoplay_sdk.rag_query.watermark`** — **`ChatWatermarkScope`**, **`InboundWatermarkStore`**, **`InMemoryInboundWatermarkStore`**, **`cutoff_for_delta_activity`**, **`effective_inbound_timestamp`** for persisting “last inbound user message” time per thread and driving **delta product activity** in `assemble_rag_chat_context(..., activity_since_cutoff=...)`.
- **`autoplay_sdk.prompts.intercom_readability`** — **`INTERCOM_READABILITY_RULES`** (shared parent fragment: plain English, lists, emojis, Intercom-safe markdown), **`RULES_VERSION`**, **`READABILITY_RULES_FINGERPRINT`**.

### Changed

- Re-exports on the root package: see **`__all__`** for **query-time RAG** vs **`RagPipeline`** (ingestion).
- **`RAG_SYSTEM_PROMPT`** — version **1.2**: adds guidance flow (acknowledge → clarify if needed → guide with tips) for product how-to questions; **1.1** composed from **`INTERCOM_READABILITY_RULES`** plus Adoption-specific examples (same placeholders).
- **`RESPONSE_PROMPT`** — version **1.2**: same guidance guideline bullet as **1.1** readability alignment.
- **Event connector `INTERCOM_CHAT_PROMPT`** — version **5**: default system text includes condensed guidance framing (personalize, one clarifying question, steps/tips).
- **`assemble_rag_chat_context`:** DEBUG summary (safe lengths/flags in ``extra``) on success; single WARNING with traceback on failure before re-raising the original exception.

### Documentation

- **Query-time RAG** docs: turn lifecycle for delta activity ([`docs/sdk/chatbot-context-assembly.mdx`](docs/sdk/chatbot-context-assembly.mdx)).
- **`rag_query` observability:** [`docs/sdk/logging.mdx`](docs/sdk/logging.mdx) lists ``autoplay_sdk.rag_query.*`` loggers; [`docs/sdk/chatbot-context-assembly.mdx`](docs/sdk/chatbot-context-assembly.mdx) **Observability** section; README pointer for production tuning.

### Breaking changes

None for JSON consumers: new keys are optional and default to absent / null.

---

## [0.6.5] — 2026-04-23

### Changed

- **`onboard_product`** / **`onboard_product_sync`** require a **`contact_email`** keyword argument (valid email string). The event connector **`POST /products`** API requires **`contact_email`** on every new registration and re-registration.
- **Render `PRODUCTS_CONFIG`:** `contact_email` is normalized on every row written via the SDK (including `serialize_products_config` / `put_products_config_on_render`).

### Breaking changes

- Call sites must pass **`contact_email=`** when using **`onboard_product`** / **`onboard_product_sync`**, **`OnboardingRunParams`**, **`build_register_payload_from_cli`**, **`post_register_product_cli`**, and **`python scripts/onboard_customer.py`** (**`--contact-email`**).

---

## [0.6.4] — 2026-04-23

### Added

- **`SlimAction`** — optional per-action identity fields: `session_id`, `user_id` (PostHog distinct / identified id), and `email`, in line with batch-level `ActionsPayload` fields. Each object in `actions` lists (SSE stream, push webhook JSON, and `ActionsPayload.from_dict` parsing) can include this metadata.
- **`RedisEventBuffer`** — JSON serialization for Redis storage now includes the new per-action identity fields on each action so drain/round-trip does not strip them.

### Documentation

- **Payload schema** and **Typed payloads** — per-action `session_id` / `user_id` / `email` documented; payload schema notes that push webhooks use the same `actions` object shape as the SSE stream.

### Breaking changes

None. New fields are optional and default to `None` when absent from JSON.

---

## [0.6.2] — 2026-04-16

### Added

- **Interactive terminal UX for `POST /products`** (`post_register_product_payload`) — when stdout is a TTY, shows a Rich stderr spinner during registration and prints success or failure on stdout; suppressed in CI and non-interactive runs.

### Changed

- **`run_product_onboarding`** performs a **single** `POST /products` to the connector. The connector dual-writes Redis + Render `PRODUCTS_CONFIG` when `RENDER_API_KEY` / `RENDER_SERVICE_ID` are set on the connector; `OnboardingRunResult.render_sync_performed` is true when the connector response includes `dual_write`.
- **`unkey.py` is now a default dependency** — `pip install autoplay-sdk` installs everything needed for `autoplay_sdk.admin` / `onboard_product` (Unkey key creation), without an extra.

### Removed

- **`[admin]` optional extra** — use `pip install autoplay-sdk` (not `autoplay-sdk[admin]`).

---

## [0.6.1] — 2026-04-14

### Added

- **`ConversationEvent`** (`autoplay_sdk.chatbot`) — dataclass produced by chatbot session-link webhook parsing (`conversation_id`, `external_id`, `email`).
- **`BaseChatbotWriter` session-link webhook flow** — `SESSION_LINK_WEBHOOK_TOPICS`, `extract_conversation_event()` (topic allowlist + dispatch), and `_parse_session_link_webhook_payload()` hook (default `None`). Platform subclasses override only `_parse_session_link_webhook_payload`; do not override `extract_conversation_event`.
- **`autoplay_sdk.integrations.intercom`** — `INTERCOM_WEBHOOK_TOPICS`, `intercom_chatbot_webhook_url()`, optional `format_reactive_session_link_script()` for copy-paste reactive Intercom setup. This subpackage does **not** emit log records.

### Removed

- **`format_proactive_session_start_script`** and the proactive **`/sessions/start`** snippet template — Intercom linking is webhook-driven (`POST /chatbot-webhook/{product_id}`). Use `intercom_chatbot_webhook_url()` and `INTERCOM_WEBHOOK_TOPICS`; optional **`format_reactive_session_link_script`** remains for `POST /sessions/link` if you still need browser-assisted linking.

### Documentation

- **Logging** — [Logging reference](docs/sdk/logging.mdx): logger hierarchy under `autoplay_sdk.*`, application-owned configuration (the SDK does not call `logging.basicConfig`), guidance for third-party `BaseChatbotWriter` subclasses, and cross-link to this changelog for observability history.
- **README** — Logging section expanded with hierarchy note, link to the logging reference, and pointer to `SdkMetricsHook` for metrics alongside logs.
- **[Intercom integration](docs/integrations/intercom.mdx)** — SDK reference (webhook topics, URL builder, optional reactive `/sessions/link` snippet).

### Breaking changes

- Importing or calling **`format_proactive_session_start_script`** from `autoplay_sdk.integrations.intercom` raises `AttributeError` (symbol removed).

### Deprecations

None.

---

## [0.6.0] — 2026-04-13

### Documentation

- **BaseChatbotWriter — Note body format** — Mintlify [chatbot-writer](https://github.com/Autoplay-AI/Autoplay-proactive-visual-customer-support/blob/main/./docs/sdk/chatbot-writer.mdx) now documents the full plain-text contract for `_post_note` bodies (header via `format_chatbot_note_header`, sorted 1-based action lines, binning vs post-link, empty list, summary notes). `_format_note` docstring points to that page as the single source of truth.

- **Logging** — New [logging](https://github.com/Autoplay-AI/Autoplay-proactive-visual-customer-support/blob/main/./docs/sdk/logging.mdx) reference page (module loggers, `%` formatting, `exc_info`, structured `extra`, secrets guidance including HTTP bodies, common logging mistakes). Quickstart links to it for discoverability.

### Bug fixes / observability

- `BaseChatbotWriter` — pre-link flush failure `warning` now includes structured `extra` (`session_id`, `product_id`, `conversation_id`).

- `BaseChatbotWriter` — post-link debounced flush: if `_post_note` returns no part id after the debounce buffer was popped, logs a `warning` with the same `extra` shape and explains that this flush is not retried automatically.

### Breaking changes

None.

### Deprecations

None.

---

## [0.5.0] — 2026-04-10

### New features

- **`ActionsPayload.merge(payloads)`** — class method that merges a non-empty list of `ActionsPayload` objects for the same session into one. Actions are concatenated and re-indexed from `0`; `user_id`/`email` resolved from the first non-`None` value; `forwarded_at` set to the latest timestamp. Raises `ValueError` on empty input.

- **`AsyncAgentContextWriter(debounce_ms=N)`** — new optional constructor parameter for a per-session trailing-edge accumulation window. When `> 0`, multiple `add()` calls arriving within the window are merged via `ActionsPayload.merge()` before `write_actions` is called, reducing destination API calls during event bursts. Default is `0` (no debounce — existing behaviour unchanged).

- **`BaseChatbotWriter`** (`autoplay_sdk.chatbot`) — new public base class providing the complete pre-link/post-link delivery policy for building chatbot destinations. Subclass it and implement `_post_note` and `_redact_part`; pre-link buffering (sliding window), at-link flush (binned note), and post-link debouncing are all included. `IntercomChatbot` in the event connector already extends this class.

### Breaking changes

None. All changes are additive:

- `AsyncAgentContextWriter.__init__` gains `debounce_ms: int = 0` — existing code passing positional or keyword arguments is unaffected.
- `ActionsPayload.merge()` is a new class method; no existing method is renamed or removed.
- `BaseChatbotWriter` is a new public export; no existing symbols are removed.

### Deprecations

None.

### Bug fixes / error handling improvements

- `BaseChatbotWriter.on_session_linked` — now no-ops when the same `conversation_id` is passed again (idempotent guard). The product worker includes the conv_id on every batch for already-linked sessions; without this guard, each batch would cancel the in-flight 150ms post-link debounce task and restart the window, causing notes to be delayed indefinitely during fast user interactions.

- `BaseChatbotWriter.on_session_linked` — pre-link buffer (`_pending`) is now only cleared after `_post_note` confirms success (returns a non-`None` part id). Previously the buffer was popped before the API call; a transient Intercom failure would permanently lose those events. On failure the buffer is now preserved and the `_conv_map` entry is rolled back so the next `on_session_linked` call retries automatically.

- `BaseChatbotWriter.write_actions`: the post-link debounce `asyncio.Task` now has a `done_callback` that logs any unhandled exception at `ERROR` level with structured `extra` (previously silent — Python only emitted a `DEBUG`-level "Task exception was never retrieved").

- `AsyncAgentContextWriter._flush_session` done-callback: now includes `product_id` in the log message and `extra` dict for structured log filtering.

### Migration notes

**`AsyncAgentContextWriter` + `BaseChatbotWriter` — avoid double-debouncing**

`BaseChatbotWriter` already coalesces rapid `write_actions()` calls via its `post_link_debounce_s` window (default 150 ms). When wiring an `AsyncAgentContextWriter` to a `BaseChatbotWriter` subclass, keep `debounce_ms=0` (the default):

```python
# CORRECT — BaseChatbotWriter handles debouncing; no stacking needed
writer = AsyncAgentContextWriter(
    summarizer=summarizer,
    write_actions=chatbot_subclass.write_actions_cb,
    overwrite_with_summary=overwrite_cb,
    debounce_ms=0,   # ← default, explicit for clarity
)

# AVOID — stacks two debounce windows, adds latency without benefit
writer = AsyncAgentContextWriter(..., debounce_ms=200)
```

Use `debounce_ms > 0` only when `write_actions` points to a raw destination with no internal coalescing (e.g. a direct Zendesk or Salesforce API call).

---

## [0.4.0] — 2026-04-09

### Bug fixes

- Fixed TOCTOU race in `RedisEventBuffer._get_redis()`: concurrent callers could each create their own connection pool; now serialised with `asyncio.Lock` and double-checked locking.
- Fixed `AsyncSessionSummarizer.flush()` cancellation safety: replaced sequential `for q in queues: await q.join()` with `asyncio.gather(*[asyncio.shield(q.join()) for q in queues])` so all queues are drained even when the caller is cancelled.

### Other

- Added `CHANGELOG.md` to document breaking changes and new features going forward.

---

## [0.3.0] — 2026-04-09

### Breaking changes

- **`AsyncSessionSummarizer.get_context(session_id)` is now `async`** — callers must `await` it.
- **`AsyncSessionSummarizer.reset(session_id)` is now `async`** — callers must `await` it.
- **`AsyncSessionSummarizer.active_sessions` is now an `async` property** — callers must `await` it.
- **`AsyncSessionSummarizer.add()` now returns immediately** — the LLM call is dispatched to a background worker queue rather than awaited inline. Code that relied on the LLM having completed by the time `await add()` returned must call `await summarizer.flush()` before inspecting state.

### New features

- **`AsyncSessionSummarizer.flush()`** — waits for all queued payloads to be fully processed; cancellation-safe via `asyncio.gather` + `asyncio.shield`.
- **`SdkMetricsHook` protocol** (`autoplay_sdk.metrics`) — a `@runtime_checkable Protocol` that customers can implement to receive Prometheus / Datadog / OTEL counters for: dropped events, summarizer latency, Redis operation latency, queue depth, and semaphore timeouts.
- **`metrics=` constructor parameter** on `ConnectorClient`, `AsyncConnectorClient`, `AsyncSessionSummarizer`, and `RedisEventBuffer`.
- **`initial_backoff_s`, `max_backoff_s`, `max_retries` constructor parameters** on both SSE clients — exposes and documents the reconnect policy with configurable jitter-backed exponential backoff.
- **Per-session ordering guarantee in `AsyncSessionSummarizer`** — each session now has its own `asyncio.Queue` + background `asyncio.Task` worker, ensuring that concurrent `add()` calls for the same session are always processed in arrival order, even if an earlier LLM call fails.
- **`py.typed` marker** — the package is now PEP 561-compliant; static type-checkers will find type stubs automatically.

### Bug fixes (v0.2.x → v0.3.0)

The following 24 items were addressed across two audit passes:

**Concurrency & correctness**
- Fixed `AsyncSessionSummarizer` ordering bug: concurrent adds during an LLM failure could produce out-of-order `on_summary` callbacks (replaced single lock with per-session queue).
- Fixed TOCTOU race in `RedisEventBuffer._get_redis()`: concurrent callers could each create their own connection pool; now serialised with `asyncio.Lock` and double-checked locking.
- Replaced `asyncio.Semaphore._value` (private API, breaks across CPython minor versions) with an explicit `_TrackedSemaphore` counter.
- Replaced `asyncio.get_event_loop()` (deprecated) with `asyncio.get_running_loop()` in `app.py` and `async_client.py`.
- Replaced `asyncio.ensure_future()` with `loop.create_task()` in `async_client.py`.
- Added `done_callback` on fire-and-forget `asyncio.Task`s to log unhandled exceptions instead of silently swallowing them.

**Error handling**
- `RedisEventBuffer._payload_from_json()` now wraps `json.loads` in `try/except json.JSONDecodeError`; corrupt ZSET members no longer crash the drain loop.
- `ConnectorClient` now sets `self._running = False` on `KeyboardInterrupt` so callers can inspect the state after shutdown.
- All `except` clauses that were swallowing exceptions now pass `exc_info=True` to the logger so tracebacks appear in structured logs.

**Data structures**
- `RedisEventBuffer` ZSET members now carry a unique UUID prefix, preventing silent deduplication when two events arrive at the same millisecond timestamp.
- `SessionSummarizer` now deletes `_history[session_id]` and `_counts[session_id]` after summarisation to prevent unbounded memory growth.
- `AsyncConnectorClient._session_semaphores` changed from plain `dict` to `collections.OrderedDict` with LRU eviction to cap memory when many short-lived sessions are processed.

**Redis connection management**
- Extracted `LazyRedisClient` helper (`storage/_redis.py`) so all storage modules share one lazily-initialised, thread-safe Redis client instead of each implementing the same racy pattern.
- `session_store` now uses `LazyRedisClient` and exposes a `SessionState.from_redis_link()` classmethod that owns the full reconstruction logic (preventing silent field omissions on restore).
- `SessionState` gains an `error: Optional[str]` field to surface last-known error reason through the API.

**Logging & observability**
- Replaced custom `_JsonFormatter` in `app.py` that ignored `extra={}` fields with a correct implementation that merges them into the JSON line.
- All structured log calls now use `extra={}` dicts consistently.
- Metrics instrumentation added at every observability-relevant site: event drops, queue depth, semaphore timeouts, summarizer latency, Redis add/drain latency.

**Package hygiene**
- Added `__all__` exports to `__init__.py` so `from autoplay_sdk import *` is well-defined.
- Added `__version__ = "0.3.0"` to `__init__.py`.
- Added `py.typed` marker for PEP 561 compliance.
- Removed dead `_dropped_count` / `_total_count` metrics fields that were incremented but never surfaced.
- Standardised public API: `on_drop` callback signature is now consistent across `ConnectorClient`, `AsyncConnectorClient`, and `RedisEventBuffer`.

---

## [0.2.0] — prior

Initial internal release. No changelog maintained at this version.
