---
title: "PostHog skill"
sidebarTitle: "PostHog"
description: "Connects an existing PostHog project to Autoplay live activity. Covers verifying posthog-js initialization, identifying logged-in users with the app's stable user ID, and using onboard_product/PostHogProvider to create and verify the PostHog to Autoplay destination. Use when the customer already uses PostHog, posthog-js, posthog.identify, product_id, or asks how to send PostHog activity to Autoplay."
---

# Session Replay Provider — PostHog

> Read `autoplay-core` first. The PostHog `session_id` is the `session_id` used
> for all session scoping throughout your Autoplay integration.
>
> **Your job is ONE thing: edit the frontend code.** Install `posthog-js` if
> missing, then get a working `posthog.init` + `posthog.identify({ product_id })`
> into the app. Show diffs, confirm, write. That's it — then you're done.
>
> **Do NOT do any of these** — the `autoplay-setup` CLI already handled them, or
> handles them after you finish:
> - ❌ Create or verify the PostHog destination (the CLI provisioned it before
>   launching you — Step 4).
> - ❌ Start the dev server, run `npm install` for app dependencies, or scaffold
>   app config (`package.json`, `tsconfig.json`, pages) — you only touch the
>   PostHog init/identify wiring, nothing else.
> - ❌ Run a smoke test or check that events flow / the SSE stream connects —
>   the CLI runs the real end-to-end event check after you exit. Wiring the code
>   correctly is the whole job; confirming delivery is not yours to do.

## Step 1 — Ensure `posthog-js` is installed

Check the app's `package.json` for `posthog-js`.

- **Present** → an init likely already exists; you'll *patch* it (Step 2).
- **Missing** → install it (`npm install posthog-js`, or the project's package
  manager) and treat this as **greenfield** — you'll *scaffold* a new init.

In a **monorepo**, find the actual frontend app first (the package that renders
the browser UI and owns `posthog.init`); install and edit there, not at the root.

## Step 2 — Get the browser init + identify in place

Two paths:

- **An init already exists** → patch it: ensure `posthog.identify(...)` includes
  `product_id`. Init and identify often live in different files (init at app
  bootstrap, identify where auth state is known). See
  `references/identify-patterns.md`.
- **Greenfield (you just installed posthog-js)** → scaffold a minimal init with
  the right `api_host` + autocapture. See
  `references/scaffold-patterns.md` and the
  framework walkthroughs in `examples/` (React/Vite, Vue/Nuxt,
  Next.js).

Minimal init shape:

```javascript
import posthog from 'posthog-js'

posthog.init('YOUR_POSTHOG_PROJECT_API_KEY', {   // the public phc_… key
    api_host: 'YOUR_POSTHOG_HOST',                // MUST match where the destination lives
    person_profiles: 'identified_only',
    session_idle_timeout_seconds: 120,
})
```

**Identity is set on login (Step 3), NOT in the init.** Do **not** call
`posthog.identify(posthog.get_distinct_id(), …)` in `loaded` or anywhere — that
"identifies" the *anonymous* id and is the #1 mistake here. Until the user logs
in they are anonymous (that's correct); `session_id` still scopes everything.

**Always show edits as a diff and confirm before writing.** If you can't safely
locate or edit the init (ambiguous/unfamiliar setup), **don't guess** — fall
back to Step 5.

## Step 3 — Identify with the app's stable user id on login (REQUIRED)

This is the most important call in the integration. The moment auth knows who
the user is, pass **the application's own stable user id** as the distinct id —
never the anonymous `posthog.get_distinct_id()`:

```javascript
// On login (and on app load when restoring an already-logged-in session):
posthog.identify(user.id, {        // user.id = YOUR app's stable user id
    product_id: 'YOUR_POSTHOG_PROJECT_ID',  // your PostHog project ID — Settings → Project → General → Project ID
    email: user.email,             // recommended; enables email-based scoping
})

// On logout:
posthog.reset()                    // clears identity so the next user starts clean
```

Why this matters:
- It makes PostHog's `distinct_id` **equal to your app's user id**, so the exact
  id you use internally is the one Autoplay receives (`ActionsPayload.user_id`).
- PostHog **links the user's earlier anonymous activity** to this identified
  person — no orphaned anonymous ids after login.
- `posthog.reset()` on logout stops the next user (e.g. shared device) from
  inheriting the previous identity.

Find where auth state becomes known — after a successful login, and wherever the
app rehydrates a session for an already-logged-in user (e.g. an auth context /
`onAuthStateChanged` / session loader) — and call `identify` there with the real
user id. See `references/identify-patterns.md`.

If the app has **no auth yet** (greenfield), there is no user to identify — wire
the init now, and leave a clear comment at the auth boundary showing exactly the
`posthog.identify(user.id, …)` call to add once login exists. Do not fake it
with the anonymous id.

## Step 4 — The destination is created automatically (do NOT do this by hand)

Onboarding code creates and verifies the PostHog destination for you:

- `PostHogProvider.create_destination(...)` — idempotent: creates (or updates) the
  "Autoplay Event Stream" hog_function pointing at the connector webhook returned
  by `onboard_product`.
- `PostHogProvider.verify(...)` — confirms it exists and is enabled.

So there is **no manual "add a webhook in PostHog" step** here. If you're running
in a context where onboarding hasn't created it yet, that's an onboarding step,
not a frontend-wiring step — leave it to the code path.

## Step 5 — You're done (the CLI verifies, not you)

Once the init + identify edits are written and confirmed, **stop — you're
finished.** Do not start the dev server, do not click around the app, do not run
a smoke test, do not check the SSE stream. The `autoplay-setup` CLI runs the
real end-to-end event check itself after you exit (it watches the live stream
for the first event). Hand back with a short summary of the files you changed.

**Fallback — if you couldn't safely wire the code:** output the exact snippet for
the user to paste, then let them confirm:

```javascript
// Call this on login, with YOUR app's user id (not the anonymous id):
posthog.identify(user.id, { product_id: 'YOUR_POSTHOG_PROJECT_ID', email: user.email })
// And on logout:
posthog.reset()
```

## Common mistakes

- **Identifying the anonymous id.** `posthog.identify(posthog.get_distinct_id(),
  …)` re-stamps the anonymous id and never sets your real user id. Always pass
  the app's stable user id (Step 3).
- **Forgetting `posthog.reset()` on logout.** The next user inherits the
  previous identity on shared sessions.
- **`api_host` must match the destination's host.** If the app sends events to a
  different host than the one the destination is created on, nothing flows.
- **Monorepos:** editing the wrong package. Confirm which app owns `posthog.init`.

## Reference

- `references/identify-patterns.md` — where
  init vs identify live, per framework
- `references/scaffold-patterns.md` — greenfield
  init scaffolds
- `examples/` — React/Vite, Vue/Nuxt, Next.js walkthroughs
- Quickstart: https://developers.autoplay.ai/quickstart
- PostHog identify docs: https://posthog.com/docs/product-analytics/identify
