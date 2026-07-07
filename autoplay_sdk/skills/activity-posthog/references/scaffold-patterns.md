# scaffold-patterns

The **minimal recommended** PostHog browser init to create when an app has
`posthog-js` installed but no existing `posthog.init` (the greenfield path).
Goal: a working init with the right `api_host` and autocapture left
on — that alone produces the `$session_id` events the Autoplay destination
forwards. Do **not** add an `identify` call here; greenfield apps have no user
to identify, and routing to Autoplay is by the destination's product webhook,
not by anything in this code.

Rules that apply to every framework below:

- Read the key and host from **public env vars**; never hardcode them.
- The `api_host` value MUST match your PostHog host — the same host the
  Autoplay destination is created on (else events go one place, the destination
  listens elsewhere, and nothing flows).
- Match the project's language: write `.js`/`.jsx` for a JavaScript app
  (`jsconfig.json`, no `tsconfig.json`), `.ts`/`.tsx` for TypeScript.
- Leave autocapture at its default (on). Don't disable `capture_pageview`.
- Adapt to the app's real files — the snippets below are canonical shapes, not
  literal drop-ins. Preserve the customer's existing `layout`/`main`/root.

---

## Next.js — App Router

Env vars: `NEXT_PUBLIC_POSTHOG_KEY`, `NEXT_PUBLIC_POSTHOG_HOST`.

### `app/providers.jsx` (JS) — new client provider

```jsx
"use client";

import posthog from "posthog-js";
import { PostHogProvider as PHProvider } from "posthog-js/react";
import { useEffect } from "react";

export function PostHogProvider({ children }) {
  useEffect(() => {
    posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
      capture_pageview: true,
      person_profiles: "identified_only",
    });
  }, []);

  return <PHProvider client={posthog}>{children}</PHProvider>;
}
```

TypeScript (`app/providers.tsx`) is identical except the signature:
`{ children }: { children: React.ReactNode }`.

### `app/layout.jsx` — mount the provider around `{children}`

Edit the existing root layout; keep everything already there (metadata,
`<html>`/`<body>`, fonts, theme providers). Only wrap the children:

```jsx
import { PostHogProvider } from "./providers";

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <PostHogProvider>{children}</PostHogProvider>
      </body>
    </html>
  );
}
```

If the layout already nests other providers, mount `PostHogProvider` as the
outermost one so analytics is available everywhere.

---

## Next.js — Pages Router

Env vars: same as App Router. Initialize once in `pages/_app.{js,tsx}` and wrap
the tree in `PHProvider`:

```jsx
import posthog from "posthog-js";
import { PostHogProvider as PHProvider } from "posthog-js/react";
import { useEffect } from "react";

export default function App({ Component, pageProps }) {
  useEffect(() => {
    posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
      capture_pageview: true,
      person_profiles: "identified_only",
    });
  }, []);

  return (
    <PHProvider client={posthog}>
      <Component {...pageProps} />
    </PHProvider>
  );
}
```

---

## Vite + React

Env vars: `VITE_POSTHOG_KEY`, `VITE_POSTHOG_HOST` (Vite exposes only `VITE_*` to
the client, via `import.meta.env`). Wrap the root in `src/main.{jsx,tsx}`:

```jsx
import posthog from "posthog-js";
import { PostHogProvider } from "posthog-js/react";

posthog.init(import.meta.env.VITE_POSTHOG_KEY, {
  api_host: import.meta.env.VITE_POSTHOG_HOST,
  capture_pageview: true,
  person_profiles: "identified_only",
});

// then wrap your <App /> in <PostHogProvider client={posthog}> … </PostHogProvider>
```

`.env` additions: `VITE_POSTHOG_KEY=...`, `VITE_POSTHOG_HOST=...`.

---

## Nuxt 3

Env vars via `runtimeConfig.public`: `NUXT_PUBLIC_POSTHOG_KEY`,
`NUXT_PUBLIC_POSTHOG_HOST`. Create a client plugin
`plugins/posthog.client.js`:

```js
import posthog from "posthog-js";

export default defineNuxtPlugin((nuxtApp) => {
  const cfg = useRuntimeConfig();
  const client = posthog.init(cfg.public.posthogKey, {
    api_host: cfg.public.posthogHost,
    capture_pageview: true,
    person_profiles: "identified_only",
  });
  return { provide: { posthog: client } };
});
```

Add `posthogKey` / `posthogHost` under `runtimeConfig.public` in
`nuxt.config.ts` (Nuxt maps `NUXT_PUBLIC_POSTHOG_KEY` → `public.posthogKey`).

---

## After scaffolding (all frameworks)

The `.env.local` (or `.env`) gets the public key + host so the init resolves
them at build time — the public **Project API key** (`phc_…`) → the
`*_POSTHOG_KEY`, your **PostHog host** → the `*_POSTHOG_HOST`. Show the new
file(s) and env additions as a diff and confirm before writing, then restart
the dev server and confirm events start flowing.
