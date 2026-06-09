# autoplay-migrate-imports

Use this skill when asked to migrate autoplay-sdk imports from 0.7.3 to 0.7.4+.

## Rules
- Do not modify `from autoplay_sdk import ...` imports.
- Update only deprecated paths listed in the mapping table below.
- Verify with tests using `-W error::DeprecationWarning`.

## Discovery
Use ripgrep to find old imports:

```bash
rg "from autoplay_sdk\." -g "*.py" \
  | rg -v "from autoplay_sdk\.(core|chat|context|proactive|agent_state|api|rag|admin|integrations|skills|prompts|compat)(\.|\s)" \
  | rg -v "from autoplay_sdk import"
```

`autoplay_sdk.rag` is stable in `0.7.4` and intentionally excluded from migration.

## Replacements

| Old path | New path |
|---|---|
| `autoplay_sdk.serve.fastapi` | `autoplay_sdk.api.fastapi` |
| `autoplay_sdk.proactive_triggers` | `autoplay_sdk.proactive.triggers` |
| `autoplay_sdk.agent_states` | `autoplay_sdk.agent_state.v1.states` |
| `autoplay_sdk.agent_state_v2` | `autoplay_sdk.agent_state.v2.states` |
| `autoplay_sdk.rag_query` | `autoplay_sdk.rag.query` |
| `autoplay_sdk.agent_context` | `autoplay_sdk.context.agent_context` |
| `autoplay_sdk.context_store` | `autoplay_sdk.context.context_store` |
| `autoplay_sdk.models` | `autoplay_sdk.core.models` |
