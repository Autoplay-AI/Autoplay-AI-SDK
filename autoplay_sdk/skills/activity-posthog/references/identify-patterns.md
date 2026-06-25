# identify-patterns

How PostHog initialization and `identify` show up in real codebases, and for
each: how to recognize it, where `identify` lives, what to patch, and what NOT
to touch. The goal of the patch is always the same: ensure the `identify` call
carries a `product_id` property equal to `POSTHOG_PROJECT_ID`, sourced from a
public env var. Never overwrite an existing init/identify — add alongside.

The product-id env var name follows the framework:
`NEXT_PUBLIC_AUTOPLAY_PRODUCT_ID` (Next.js), `VITE_AUTOPLAY_PRODUCT_ID` (Vite),
`NUXT_PUBLIC_AUTOPLAY_PRODUCT_ID` (Nuxt).

---

## 1. Next.js App Router — `src/instrumentation-client.ts`

**Recognize:** Next.js 14+, `posthog.init(...)` in `src/instrumentation-client.ts`
(or `instrumentation-client.ts` at root). `identify` is usually in a `"use client"`
provider/component mounted by the root layout.

**Patch:** add `product_id` to the existing `identify` properties object.

BEFORE:
```ts
posthog.identify(user.id, { email: user.email });
```
AFTER:
```ts
posthog.identify(user.id, {
  email: user.email,
  product_id: process.env.NEXT_PUBLIC_AUTOPLAY_PRODUCT_ID,
});
```
See `examples/nextjs-typescript.md`. Do not touch the `posthog.init` call beyond
the api_host check in Step 5b.

## 2. Next.js Pages Router — `pages/_app.tsx`

**Recognize:** `posthog.init(...)` inside `pages/_app.tsx`, often guarded by
`if (typeof window !== "undefined")`. `identify` is typically in a `useEffect`
in `_app.tsx` after the user/session resolves.

**Patch:** same as pattern 1 — add `product_id` to the identify properties.

## 3. Vite + React — `src/main.tsx`

**Recognize:** `posthog.init(...)` near the React root in `src/main.tsx`, or in a
`src/analytics.ts`/`src/lib/posthog.ts` imported there. Env var is
`import.meta.env.VITE_*`.

**Patch:** add `product_id: import.meta.env.VITE_AUTOPLAY_PRODUCT_ID` to the
identify properties. See `examples/react-vite.md`.

## 4. Nuxt 3 — `plugins/posthog.client.ts`

**Recognize:** `posthog.init(...)` inside a `defineNuxtPlugin(...)` in
`plugins/posthog.client.ts`; the client is provided as `$posthog`.

**CRITICAL — the identify call is `$posthog.identify(`, NOT `posthog.identify(`.**
A literal grep for `posthog.identify` will MISS it. Nuxt code reads the client
off `useNuxtApp()` and calls identify on the `$`-prefixed handle, usually in
`app.vue` `onMounted`:

```ts
const { $posthog } = useNuxtApp();
$posthog.identify(user.id, { email: user.email });
```

So Step 5c's search must include the `$posthog.identify(` form (the
`(posthog|\$posthog|ph|analytics)\.identify\(` regex covers it).

**Patch:** add `product_id` to the identify properties, sourced from runtime
config — expose `autoplayProductId` in `nuxt.config.ts` `runtimeConfig.public`
and read `useRuntimeConfig().public.autoplayProductId`. See `examples/vue-nuxt.md`:

```ts
const config = useRuntimeConfig();
$posthog.identify(user.id, {
  email: user.email,
  product_id: config.public.autoplayProductId,
});
```

## 5. Segment-wrapped PostHog (CRITICAL — do not modify the wrapper)

**Recognize:** `@segment/analytics-next` in `package.json`,
`AnalyticsBrowser.load({...})` in the code, and **no `posthog.init(` anywhere**
even though `posthog-js` is installed. PostHog is a Segment *destination*
configured in the Segment dashboard; events reach PostHog through Segment, not a
direct browser init.

**What to do:** do NOT add a `posthog.init`, and do NOT edit the Segment
`load()` call. STOP and ask the user:

> "This project routes analytics through Segment, with PostHog as a Segment
> destination — there's no direct posthog.init() to patch. Where should the
> product_id be attached to identify? Options: (a) add product_id to your
> Segment `analytics.identify(...)` traits, or (b) point me at a place you'd
> prefer. I won't change the Segment setup without your say-so."

If the user chooses (a), add `product_id` to the **traits object** of their
existing `analytics.identify(id, { ... })` call (that's their code, not the
Segment library) — show the diff and confirm as usual.

## 6. RudderStack-wrapped PostHog

**Recognize:** `rudder-sdk-js` / `@rudderstack/analytics-js`,
`rudderanalytics.load(...)`, no direct `posthog.init`. Same situation as
Segment.

**What to do:** identical to pattern 5 — never touch the RudderStack wrapper;
ask the user where `product_id` should be attached and patch only their own
`identify`/`track` call.

## 7. PostHog used server-side too (SSR + browser)

**Recognize:** both a browser `posthog.init` (in client code) and a server-side
PostHog (`posthog-node`, or `PostHog` constructed in a route/server file).

**What to do (v0.1):** patch **only the browser init/identify**. Mention the
server-side usage to the user, but do not modify server-side init in v0.1 — ask
before touching it if the user wants it.

## 8. Monorepo workspaces — multiple apps

**Recognize:** a root `package.json` with a `workspaces` array, and/or a
`pnpm-workspace.yaml`. Multiple apps under `apps/*` or `packages/*`, each
potentially with its own PostHog setup (or none).

**What to do:** do NOT instrument blindly. List what you found, e.g.:

> "This is a monorepo. I found these apps: apps/web-marketing (no PostHog),
> apps/web-app (PostHog, US). Which one should I instrument? [path]"

Operate only on the chosen app: re-run Step 1 detection scoped to that app's
directory, and treat that directory as the working root for Steps 5–7.

---

## General rules for the patch

- The id passed to `identify` MUST be the app's **stable user id** (the one your
  auth/user object exposes), never `posthog.get_distinct_id()` or any anonymous
  id. That id is what reaches Autoplay as `user_id`.
- If there is an existing `identify(id, { ...props })`, add `product_id` to
  `props`. Keep every existing property.
- If there is an `identify(id)` with no props object, change it to
  `identify(id, { product_id: <env var> })`.
- If there is no `identify` at all, add one after auth/session resolves (on
  mount), using the user id available in that scope. If no user id is available
  anywhere, ask the user where identification happens.
- Add `posthog.reset()` where the user logs out (clears identity for the next
  user). If there's no logout handler, note it for the user rather than guessing.
- Always show the diff and get `y` before applying (SKILL.md Step 5c).
