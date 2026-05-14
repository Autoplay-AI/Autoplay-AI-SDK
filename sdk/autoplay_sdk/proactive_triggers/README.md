# Proactive triggers (`autoplay_sdk.proactive_triggers`)

Transport-agnostic **when to offer** assistance: context in, optional structured result out (`trigger_id`, copy, timings). Pair results with your delivery layer (Intercom `quick_reply`, in-app modal, etc.). Use **`ScopePolicy.STRICT`** so **`product_id`** and **`session_id`** are required on **`from_slim_actions` / `from_actions_payloads`** unless you opt into **`ScopePolicy.LENIENT`**.

## Two ways to define what fires

1. **SDK built-in catalog** — shipped triggers registered in `builtin_catalog` (e.g. **canonical URL ping-pong**, **`user_page_dwell`**, **section playbook match**). The event connector selects them via **`integration_config.proactive_triggers.builtins`** (ordered list) or the implicit default registry when **`builtins`** is omitted/empty (default registry is ping-pong only). There is no separate “legacy” trigger engine — only this catalog.

2. **Your own triggers in code** — implement **`ProactiveTrigger`** or use **`PredicateProactiveTrigger`**, build **`ProactiveTriggerRegistry([...])`** in your application. JSON product config does **not** load custom triggers; that path is code-only.

Built-in triggers may call helpers in `autoplay_sdk.integrations.intercom` for predicates that mirror Messenger recipes.

## Building a new proactive trigger

| Goal | What to do |
|------|------------|
| **One-off custom rule in your service** | Use **`PredicateProactiveTrigger`** (boolean on **`ProactiveTriggerContext`**) or implement **`ProactiveTrigger`**; optionally wrap with **`ProactiveTriggerEntity(inner, ProactiveTriggerTimings(...))`**; register in **`ProactiveTriggerRegistry`**; call **`evaluate_first`**. |
| **Selectable from Autoplay product JSON** | Add a **`BuiltinTriggerCatalogEntry`** (**`id`**, **`name`**, **`description`** — all required strings — plus timings and factory) to **`BUILTIN_TRIGGER_CATALOG`**. Operators pass rows **`{ "id", "name", "description", ... }`** in **`integration_config.proactive_triggers.builtins`**. |
| **Only use shipped ping-pong** | Omit **`builtins`** / use **`[]`** for default registry, or set **`builtins`** to a non-empty list (each row must include **`id`**, **`name`**, **`description`**). |

## Default values (when not set)

Defined on **`autoplay_sdk.proactive_triggers.types`**:

| Setting | Default |
|---------|---------|
| **`interaction_timeout_s`** (result / timings / ping-pong catalog) | **10** s — **`DEFAULT_INTERACTION_TIMEOUT_S`** |
| **`cooldown_s`** | **30** s — **`DEFAULT_COOLDOWN_S`** |
| **`ProactiveTriggerContext.from_actions_payloads`**: **`lookback_seconds`** | **120** s — **`DEFAULT_PROACTIVE_CONTEXT_LOOKBACK_S`** |
| Same: **`max_actions`** | **50** — **`DEFAULT_PROACTIVE_CONTEXT_MAX_ACTIONS`** |

In **`integration_config.proactive_triggers.builtins`**, each row **must** include **`id`**, **`name`**, and **`description`** (strings). Omitted **`interaction_timeout_s`** / **`cooldown_s`** resolve from the **catalog entry** for that **`id`** (today ping-pong uses the same 10 / 30 unless overridden in JSON).

### `user_page_dwell` tuning (defaults developers can override)

Implemented in **`triggers/user_page_dwell.py`**. The trigger uses the **trailing streak** of **`recent_actions`** on the **same `canonical_url`** as the latest action. It fires only if dwell time and sparse-action rules both pass.

| Input (`context_extra` or **`integration_config.proactive_triggers`**) | Default | Meaning |
|------------------------------------------------------------------------|---------|---------|
| **`dwell_threshold_seconds`** | **60** | Minimum seconds on that URL streak (one minute by default). |
| **`user_page_dwell_max_actions`** | **5** | Maximum actions on that streak; more actions ⇒ no fire (not “sparse”). |
| **`dwell_proactive_body`** | *(short default copy)* | Optional proactive message body when the trigger fires. |

Optional **`eval_now`** in **`context_extra`** for deterministic tests. Public docs: **`docs/sdk/proactive-triggers.mdx`**.

See **`docs/sdk/proactive-triggers-authoring.mdx`** for narrative docs and connector-level **`mode`** defaults.

## Built-in catalog (SDK)

- **`list_builtin_trigger_catalog()`** — defaults per built-in: **`id`**, **`name`**, **`description`**, **`interaction_timeout_s`**, **`cooldown_s`** (for docs and admin UIs).
- **`resolve_builtin_specs(specs)`** — merge JSON rows with catalog defaults → **`ResolvedBuiltinTriggerSpec`** (effective timings plus **`name`** / **`description`** from each row). Invalid rows raise **`SdkConfigError`** and emit a structured **`logging`** **ERROR** with **`extra["event"]="proactive_builtin_spec_invalid"`** (same for **`registry_from_builtin_specs`**).
- **`registry_from_builtin_specs(specs)`** — ordered **`ProactiveTriggerRegistry`**; **first matching trigger wins** (`evaluate_first`). Unknown **`id`** raises **`SdkConfigError`**.
- **`BUILTIN_TRIGGER_CATALOG`** / **`BuiltinTriggerCatalogEntry`** — metadata and factories for each SDK built-in (extend the catalog when adding new prebuilt triggers).

The event connector reads **`integration_config.proactive_triggers.builtins`** and calls **`registry_from_builtin_specs`** when that list is non-empty.

See [Intercom integration](../../docs/integrations/intercom.mdx), [Authoring proactive triggers](../../docs/sdk/proactive-triggers-authoring.mdx), and [Agent session states](../agent_states/README.md).

## Scoping ping-pong to URL prefixes

Use **`canonical_urls_touch_substring(canonical_urls, substring)`** (`url_scope.py`) before or after **`canonical_url_ping_pong`** evaluation so hesitation detection only counts when recent **`canonical_url`** values contain a path prefix (e.g. your **Projects** area). **`filter_ping_pong_hits_by_canonical_url_contains`** applies the same gate to a list of **`ProactiveTriggerResult`** hits.

For a composed trigger in-process, **`ScopedCanonicalPingPongTrigger`** (`triggers/scoped_canonical_ping_pong.py`) chains oscillation + substring checks.

## Stacked `quick_reply` (chips → follow-up Yes / No)

Some journeys send an initial proactive **`quick_reply`** with several chips, then a **second** admin **`quick_reply`** whose **`reply_options`** are **`Yes`** / **`No`** (see **`match_quick_reply_label`** / **`messages_match_quick_reply_pair`** in **`quick_reply_match.py`**). Match inbound Messenger text with **strip + casefold** parity with chip labels.

## Pending tour offer (optional host state)

**`PendingTourOffer`** (`pending_tour_offer.py`) is a minimal **`flow_id`** holder for “show you?” opt-ins — persist in Redis or similar on the host; clear on **No**, expiry, or after broadcasting **`usertour_trigger`** on **Yes**. Helpers for SSE payload typing live in **`autoplay_sdk.integrations.usertour_sse`**.
