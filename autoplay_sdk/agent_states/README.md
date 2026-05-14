# Agent session states (`autoplay_sdk.agent_states`)

This package is a **small, stdlib-only** finite-state machine (FSM) for **session-level** copilot behavior: whether the user is driving the turn, the assistant offered help unsolicited, a walkthrough is running, or the system is in a conservative backoff. It is **not** the same as LangGraph-style chat graph nodes.

## The five states

| State (wire value) | Meaning |
| --- | --- |
| `thinking` | Baseline between signals. Proactive offers are evaluated only when it makes sense (see `can_show_proactive_with_reason`). |
| `reactive_assistance` | The user messaged the assistant; normal reactive reply path. |
| `proactive_assistance` | The assistant surfaced an unsolicited offer (copy/UI). |
| `guidance_execution` | The user accepted an offer; step-by-step guidance is active. |
| `conservative_assistance` | Backoff after dismissals or after **disengagement** from an active guidance flow. |

Typical flows:

- User chats: `thinking` → `reactive_assistance` → (often back to) `thinking`.
- Proactive offer: `thinking` → `proactive_assistance` → user accepts → `guidance_execution` → on success or exit, `thinking` (or `conservative_assistance` if they disengage / dismiss).

Allowed edges are defined in `state_machine.py` (`_VALID_TRANSITIONS`). Illegal moves raise `InvalidTransitionError`.

## API you will use

- **`AgentStateMachine`** — holds `state`, metrics, task progress, cooldowns, and helpers such as:
  - **`transition_to(...)`** — move to a new `AgentState` if the edge is allowed.
  - **`transition_on_disengagement()`** — from `guidance_execution` only, move to `conservative_assistance` when the user abandons the flow.
  - **`can_show_proactive_with_reason()`** / **`can_show_proactive()`** — gate unsolicited offers (includes conservative cooldown handling).
  - **`to_snapshot()`** / **`from_snapshot(data)`** — JSON-serializable dict for persistence (version field `_v` for forward compatibility).
- **`TaskProgress`**, **`SessionMetrics`**, **`InvalidSnapshotError`**, **`InvalidTransitionError`** — see `types.py` and `state_machine.py`.

Logging follows [`docs/sdk/logging.mdx`](../../docs/sdk/logging.mdx): logger **`autoplay_sdk.agent_states.state_machine`**, lazy `%` formatting, structured **`extra`** with stable **`event_type`** keys (`agent_state_transition`, `agent_state_transition_rejected`, `agent_states_snapshot_invalid`, etc.). **Debug** records normal transitions and rejected transitions; **warning** + **`exc_info`** on snapshot restore failures and skipped task rows — no user payload or secrets.

## Redis and this package

**The SDK does not connect to Redis.** It only provides the FSM and snapshot serialization so your **host application** (or the Autoplay event connector) can store and restore state.

In this repository, **Intercom** integration persists the FSM in the event connector:

- **Module:** `event_connector.storage.intercom_agent_state_store`
- **Key pattern:** `connector:intercom:agent_state:{product_id}:{conversation_id}`
- **Value:** `json.dumps(machine.to_snapshot())` with a TTL (`session_ttl_s` from connector settings).
- **Process cache:** When Redis is healthy, a small in-memory cache is updated after a successful read/write so hot paths stay fast. If `REDIS_URL` is set but Redis is **unreachable**, loads return a **fresh** machine in `thinking` (no stale process cache for that key), and saves do not update the in-process cache until Redis is available again—so behavior stays consistent when Redis recovers.
- **No Redis URL (e.g. empty `REDIS_URL`):** the connector can keep snapshots **in memory only** for local development; that is not shared across processes or restarts.

If you embed the SDK elsewhere, call `to_snapshot()` after changes and pass the dict to your own store; on the next request, `AgentStateMachine.from_snapshot(data)` rebuilds the machine.

## Further reading

- User-facing overview: `docs/sdk/agent-states.mdx` in the `customer_sdk` docs package.
- Changelog: `customer_sdk/CHANGELOG.md` (search for `agent_states`).
