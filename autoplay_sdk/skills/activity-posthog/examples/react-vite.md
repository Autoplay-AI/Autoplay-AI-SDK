# Example: Vite + React (clean, direct PostHog)

A standard Vite + React app that initializes PostHog directly (no Segment).
Init typically sits in `src/main.tsx` or a small `src/analytics.ts` imported
there; env vars use the `VITE_` prefix and `import.meta.env`. The patch adds
`product_id` to identify and a `VITE_AUTOPLAY_PRODUCT_ID` env var.

> Note: the `vite-react-with-segment-wrapping-posthog` fixture is the *opposite*
> case — Segment wraps PostHog and there is no `posthog.init`. Do not use this
> example for that one; see `references/identify-patterns.md` pattern 5.

## `src/analytics.ts` — init unchanged

```ts
import posthog from "posthog-js";

posthog.init(import.meta.env.VITE_POSTHOG_KEY, {
  api_host: import.meta.env.VITE_POSTHOG_HOST,
  person_profiles: "identified_only",
});

export { posthog };
```

(If `api_host` is an env expression like above, Step 5b checks
`VITE_POSTHOG_HOST` in the customer's `.env` against `POSTHOG_HOST`, not a string
literal.)

## The identify call — patch

BEFORE (e.g. in `src/App.tsx`, after auth resolves):
```tsx
import { useEffect } from "react";
import { posthog } from "./analytics";

useEffect(() => {
  posthog.identify(user.id, { email: user.email });
}, [user.id]);
```

AFTER:
```tsx
import { useEffect } from "react";
import { posthog } from "./analytics";

useEffect(() => {
  posthog.identify(user.id, {
    email: user.email,
    product_id: import.meta.env.VITE_AUTOPLAY_PRODUCT_ID,
  });
}, [user.id]);
```

## `.env` / `.env.local` — add the product-id var

```
VITE_AUTOPLAY_PRODUCT_ID=12345
```

Show both diffs and confirm `[y/n]` before applying.
