# autoplay-migrate-imports

Use this skill when asked to migrate autoplay-sdk imports from 0.7.3 to 0.7.4+.

## Rules
- Do not modify `from autoplay_sdk import ...` imports.
- Update only deprecated paths listed in the changelog mapping table.
- Verify with tests using `-W error::DeprecationWarning`.

## Discovery
Use ripgrep to find old imports:

```bash
rg "from autoplay_sdk\." -g "*.py" \
  | rg -v "from autoplay_sdk\.(core|chat|context|proactive|agent_state|api|rag|admin|integrations|skills|prompts|compat)" \
  | rg -v "from autoplay_sdk import"
```

`autoplay_sdk.rag` is stable in `0.7.4` and intentionally excluded from migration.
