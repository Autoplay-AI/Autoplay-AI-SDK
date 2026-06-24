# Example: Next.js + TypeScript (App Router)

Anchored on the `nextjs-with-posthog-us` fixture. PostHog init lives in
`src/instrumentation-client.ts`; `identify` lives in a `"use client"` provider
mounted by the root layout. The patch adds `product_id` to identify and a public
env var; the init is left as-is (only the api_host match in Step 5b is checked).

## `src/instrumentation-client.ts` — unchanged

The init is not modified. We only confirm its `api_host` matches `POSTHOG_HOST`.

```ts
import posthog from "posthog-js";

posthog.init("phc_EXAMPLEPROJECTKEY", {
  api_host: "https://us.i.posthog.com",
  person_profiles: "identified_only",
  capture_pageview: true,
});

export default posthog;
```

## `src/app/providers.tsx` — patch identify

BEFORE:
```tsx
"use client";

import { useEffect } from "react";

import { posthog } from "@/lib/posthog";

const user = { id: "user_123", email: "jane@acme.com" };

export function Providers({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    posthog.identify(user.id, { email: user.email });
  }, []);

  return <>{children}</>;
}
```

AFTER (only the identify properties change):
```tsx
"use client";

import { useEffect } from "react";

import { posthog } from "@/lib/posthog";

const user = { id: "user_123", email: "jane@acme.com" };

export function Providers({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    posthog.identify(user.id, {
      email: user.email,
      product_id: process.env.NEXT_PUBLIC_AUTOPLAY_PRODUCT_ID,
    });
  }, []);

  return <>{children}</>;
}
```

## `.env.local` — add the product-id var

Append (value equals `POSTHOG_PROJECT_ID`):

```
NEXT_PUBLIC_AUTOPLAY_PRODUCT_ID=12345
```

That's the entire frontend change: one property added to `identify`, one env var
added. Show both diffs and confirm with `[y/n]` before applying.
