---
title: "🤖 Autoplay Agentic Setup"
sidebarTitle: "🤖 Autoplay Agentic Setup"
description: "One script an AI coding agent (Claude Code, Cursor, etc.) can follow end-to-end to wire up the full Autoplay stack — Live User Activity, an AI Support Agent, and Visual User Tours — into any codebase."
name: "autoplay-agentic-setup"
---

<Tip>
  **This page is written for an AI agent, not a human reader.** Steps marked **🤖 AGENT** are things you (the agent) do autonomously by reading and editing the codebase. Steps marked **🧑 HUMAN** require the customer to do something outside the repo (click around a dashboard, copy a key) — ask them for the specific value named, don't guess it. Each 🧑 HUMAN step under "Live User Activity" and "AI Support Agents" links to an Arcade walkthrough where one exists.

  If you'd rather read the human-facing, click-through version of the same three pillars, see the [Quickstart](/quickstart).
</Tip>

<Warning>
  **Stop-and-wait rule, applies in all three pillars:** when you hit a 🧑 HUMAN step, stop and ask the customer for that exact value — then **wait for their real answer before running the next 🤖 AGENT step that depends on it.** Never invent a placeholder credential (fake API key, made-up project id, guessed webhook secret) and continue as if it were real. Concretely: don't run `onboard_product(...)` until you have the actual project id and contact email; don't create a destination/sync until the customer confirms the registration script printed real values; don't wire an MCP tool's Authentication token until they've pasted the real `mcp_key`; don't tell them a pillar is "done" until they've confirmed the human-side dashboard step (destination live, MCP tool set to Live, tour published) is actually complete. If a needed answer hasn't been given yet, pause and ask again rather than skipping ahead.
</Warning>

<Note>
  **Every step below links to a doc the moment it needs one** — a per-provider recipe, an agent skill, or an Arcade walkthrough — so neither you nor the customer has to guess. If you hit a wall a linked doc doesn't resolve, the fallback is [Discord](https://discord.gg/jCbR2tQA5); say so to the customer rather than guessing past it.
</Note>

## Install

**🤖 AGENT** — **Prerequisites: Python 3.10+.**

<Tabs>
  <Tab title="Mac / Linux">
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install autoplay-sdk
    ```
  </Tab>
  <Tab title="Windows (PowerShell)">
    ```powershell
    python -m venv .venv
    .venv\Scripts\Activate.ps1
    pip install autoplay-sdk
    ```
  </Tab>
</Tabs>

Then install [Agent skills](/get-started/agent-skills) so later edits follow the project's exact wiring pattern instead of generic guesses:

```bash
autoplay-install-skills
# or target a specific stack up front, e.g.:
autoplay-install-skills --chatbot intercom --user-activity posthog
```

Autoplay has three independent pillars. A customer can adopt one, two, or all three — they don't depend on each other, but Live User Activity is the foundation the other two build on:

1. **Live User Activity** — stream what a user is doing in the product, in real time, into Autoplay.
2. **AI Support Agent** — let the customer's existing support bot pull that activity on demand so it can answer with context.
3. **Visual User Tours** — fire an existing tour tool (Userpilot, Chameleon, etc.) at the right moment based on that activity.

See [Overview](/who-we-are/overview) for why this exists, and [Use cases](/who-we-are/use-cases) if the customer asks "what's this for."

---

## Step 0 — Understand the project

**🤖 AGENT**

Before writing any code, determine:

- **Frontend framework** — Next.js (App Router or Pages Router), Nuxt, Angular, Vue/Vite, SvelteKit, plain React, etc.
- **Auth system** — what library handles login/logout, and how to get the current user's stable id, email, and name at the moment of login.
- **Env var conventions** — `NEXT_PUBLIC_`, `VITE_`, `NUXT_PUBLIC_`, `NG_APP_`, no prefix, etc. Anything read in browser code needs the framework's *public* prefix; anything server-only does not.
- **App entry point** — where SDKs get initialized once, as early as possible (`instrumentation-client.ts`, `_app.tsx`, `main.ts`, root layout, a Nuxt client plugin, etc.).
- **Package manager** — npm, yarn, pnpm, bun.
- **Existing analytics wrapper** — if you find `@segment/analytics-next` or RudderStack wrapping calls instead of a direct `posthog.init(...)`/`amplitude.init(...)`, **stop and ask the customer where to attach `product_id`** rather than adding a second, competing init call.
- **Monorepo?** — if there are multiple frontend apps, list them and ask which one to instrument. Never guess.

Do not write code until this is understood — every later step assumes you're patching existing patterns, not scaffolding fresh ones.

---

## Choose Your Path

**🧑 HUMAN** (you ask; they answer — don't infer these from the code)

Ask the customer, in order:

1. **"Which analytics / session-replay tool do you already use — PostHog, Amplitude, or FullStory?"** No strong preference? Default-recommend **PostHog** — it's the only provider with a fully automated destination setup (Path below), so there's less manual dashboard work.
2. **"Which AI support agent do you want to connect?"** List every option below **individually, one per line**, so the customer picks a specific platform — never compress this into "Intercom, Maven, or something else" or any other shorthand grouping:
   - **Intercom** — fully built, MCP-based (recommended default)
   - **Ada** — fully built, push-based
   - **Botpress** — fully built, push-based
   - **Dify** — documentation stub only, expect to build custom backend code by hand
   - **Crisp** — documentation stub only, expect to build custom backend code by hand
   - **Landbot** — documentation stub only, expect to build custom backend code by hand
   - **Tidio** — documentation stub only, expect to build custom backend code by hand
   - **Zendesk** — not built yet
   - **Rasa** — not built yet
   - **Inkeep** — not built yet
   - **Maven** — not built yet

   No strong preference? Default-recommend **Intercom (Fin)** — it's the only platform with a complete, current **MCP** integration; the other two fully-built options use an older push-based pattern that needs more custom backend code.
3. **"Do you already use a pop-up tour / onboarding-guidance tool — Userpilot, Chameleon, Userflow, Pendo, Usertour, UserGuiding, or Told? If not, do you want to skip this pillar for now?"** This pillar is optional and additive — most customers start with just Path 1 (+ Path 2).

Then work through the matching path below. Skip paths for pillars the customer didn't pick.

---

## Path 1 — Live User Activity

### What's shared across every provider

**🤖 AGENT**

Regardless of which provider the customer picked, registration always looks like this — only the provider class and product id source change:

```python
import asyncio
from autoplay_sdk.admin import onboard_product
from autoplay_sdk.providers import PostHogProvider  # or AmplitudeProvider — see below

async def main() -> None:
    result = await onboard_product(
        "YOUR_PROVIDER_PROJECT_ID",           # the provider's own project id — Autoplay never assigns this
        contact_email="you@yourcompany.com",  # required on every call, including re-registration
        user_activity_provider=PostHogProvider(),
        print_operator_summary=True,
    )

asyncio.run(main())
```

<Note>
  **Re-registering:** a second `onboard_product` call with the same `product_id` returns **409** unless you pass `force=True`. `contact_email` is still required on the overwrite. For PostHog this also **rotates `ingest_secret`** — update the PostHog destination's `X-PostHog-Secret` header with the new value afterward.
</Note>

The identity rule that applies no matter which provider you pick: **the `user_id` an AI support agent later asks for must be byte-identical to the id the activity provider identifies the user with.** Never key on email — it's unstable. See [Identity](/activity/identity) for the full debugging checklist.

<Warning>
  **Follow exactly one of the three accordions below — whichever the customer named in Choose Your Path — and skip the other two entirely.** They install different, unrelated frontend SDKs (`posthog-js` vs `@amplitude/unified` vs none for FullStory) and register with a different provider class. Don't install more than one unless the customer explicitly says they're running two activity sources side by side.
</Warning>

<AccordionGroup>

<Accordion title="PostHog (default recommendation)" icon="/images/recipes/posthog/logo.png" iconType="image">

**🧑 HUMAN — get the Project ID and Project API Key**

Project ID (a.k.a. Team ID) is the number in `https://us.posthog.com/project/YOUR_PROJECT_ID/...` or in Project Settings — this becomes the Autoplay `product_id`. Project API Key (`phc_…` prefix, labelled "Project Token" in the UI) is under **Settings → Projects → [Project] → General**.

> 📺 [How to find your PostHog Project ID and Project API Key](https://app.arcade.software/share/uQizURhG2MTNIxQjiIA1)

<Warning>
  **Before running anything below, re-check what Step 0 told you.** If PostHog is reached through `@segment/analytics-next` or a RudderStack wrapper rather than a direct `posthog.init(...)` call, do **not** run this install or add a second, competing init — stop and ask the customer where to attach `product_id` in their existing wrapper instead.
</Warning>

**🤖 AGENT — install and wire the frontend**

```bash
npm install posthog-js
```

```javascript
import posthog from 'posthog-js'

posthog.init('YOUR_POSTHOG_PROJECT_API_KEY', {
    api_host: 'https://us.i.posthog.com', // must match the host used to create the destination below
    person_profiles: 'identified_only',
    session_idle_timeout_seconds: 120,
    loaded: (posthog) => {
        posthog.register({ product_id: 'YOUR_POSTHOG_PROJECT_ID' }); // super-property, not an identify call
    },
})

// On login — the single most important line in this whole integration:
posthog.identify(user.id, {   // user's OWN stable id — never posthog.get_distinct_id()
    product_id: 'YOUR_POSTHOG_PROJECT_ID',
    email: user.email,
})

// On logout:
posthog.reset()
```

<Warning>
  Don't call `posthog.identify(posthog.get_distinct_id(), …)` — that re-stamps the anonymous id and never sets a real user id. This is the #1 PostHog integration mistake.
</Warning>

**🤖 AGENT — register with Autoplay**

```python
from autoplay_sdk.providers import PostHogProvider
# onboard_product("YOUR_POSTHOG_PROJECT_ID", contact_email=..., user_activity_provider=PostHogProvider(), print_operator_summary=True)
```

Prints `ingest_url`, `ingest_secret` (needed next, for the PostHog destination), plus `mcp_url` / `mcp_key` (needed for verification later, and for Path 2's MCP connection).

**🧑 HUMAN — get a Personal API Key, then let the SDK create the destination (automated, unique to PostHog)**

Personal API Key (`phx_…`, different from the Project API Key above) — **Settings → [name] → Personal API keys**, scopes `project:read` + `hog_function:write`.

> 📺 [Generate your PostHog Personal API Key](https://app.arcade.software/share/lOvmHy4FeRDtjD9xBTBb)

```python
from autoplay_sdk.providers import PostHogProvider

provider = PostHogProvider()
dest = await provider.create_destination(
    host="https://us.posthog.com",             # or eu.posthog.com — must match posthog.init's api_host
    project_id="YOUR_POSTHOG_PROJECT_ID",
    personal_api_key="YOUR_PERSONAL_API_KEY",
    webhook_url="YOUR_INGEST_URL",              # ingest_url from onboard_product
    webhook_secret="YOUR_INGEST_SECRET",        # ingest_secret from onboard_product
)
status = await provider.verify(host="https://us.posthog.com", project_id="YOUR_POSTHOG_PROJECT_ID",
                                personal_api_key="YOUR_PERSONAL_API_KEY", destination_id=dest.id)
```

Idempotent — safe to re-run. If the customer would rather click through PostHog's UI by hand (or you can't run this), the full manual steps and the Hog event-body script are in the [Quickstart's PostHog section](/quickstart).

**Common mistakes:** `api_host` mismatch between `posthog.init()` and `create_destination()` (silent total failure); forgetting `posthog.reset()` on logout; editing the wrong app in a monorepo.

</Accordion>

<Accordion title="Amplitude" icon="/images/recipes/amplitude/logo.svg" iconType="image">

**🧑 HUMAN — create the project and get the API Key**

If they don't have an account: sign up at [amplitude.com](https://amplitude.com), create a project. The **API Key** shows on the welcome screen (also under **Settings → Projects → [Project] → General**).

<Warning>
  Amplitude blocks **Data → Destinations** behind a "Waiting for your events…" screen until it receives at least one live event. Complete the init step below, click around the app once, then click **Finish Setup** (or **Skip for now**) before continuing to registration.
</Warning>

**🤖 AGENT — install and wire the frontend**

```bash
npm install @amplitude/unified
```

```typescript
import * as amplitude from '@amplitude/unified';

amplitude.initAll('YOUR_AMPLITUDE_API_KEY', {
  analytics: { autocapture: true },   // required — captures clicks/page views/forms
  sessionReplay: { sampleRate: 1 },   // lower in production if needed
});
```

```typescript
// On login:
amplitude.setUserId(user.id);

const identifyObj = new amplitude.Identify();
identifyObj.set('product_id', 'YOUR_AMPLITUDE_PROJECT_ID');
identifyObj.set('email', user.email);
identifyObj.set('name', user.name);
amplitude.identify(identifyObj);

// Also link the session directly — Amplitude has no automated destination-verify step, so this
// POST is what lets Autoplay resolve session_id -> product_id immediately instead of waiting on the sync:
const sessionId = amplitude.getSessionId();
if (sessionId) {
  fetch('YOUR_CONNECTOR_URL/identify', {           // domain portion of ingest_url from registration
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: user.email, session_id: String(sessionId), product_id: 'YOUR_AMPLITUDE_PROJECT_ID' }),
  });
}

// On logout:
amplitude.reset();
```

<Warning>
  `setUserId` alone does not write `user_properties`. Without the explicit `Identify` call above, `product_id`/`email` never populate and Autoplay can't map events to the tenant.
</Warning>

**🧑 HUMAN — get the Project ID, then register**

**Settings → Projects → [Project] → Project ID.** This becomes the Autoplay `product_id`.

> 📺 [Find your Amplitude Project ID](https://app.arcade.software/share/gbMSMIenMpBYhCWbLFrh)

```python
from autoplay_sdk.providers import AmplitudeProvider
# onboard_product("YOUR_AMPLITUDE_PROJECT_ID", contact_email=..., user_activity_provider=AmplitudeProvider(), print_operator_summary=True)
```

Prints `ingest_url` and `ingest_secret` — needed next, for the destination's `Authorization` header — plus `mcp_url` / `mcp_key` for verification later. **Unlike PostHog, there is no automated destination-creation method** — the dashboard steps below are manual either way.

**🧑 HUMAN — create the Event Streaming destination**

**Data → Destinations → + Add Destination → search "HTTP" → Event Streaming.** URL = `ingest_url`. Auth header `Authorization: ${parameters.apiKey}` where `apiKey` = `Bearer ` + `ingest_secret`. Paste the Freemarker event-body template from the [Quickstart's Amplitude section](/quickstart) exactly — without it, only page views arrive; clicks and form events are silently dropped. Enable **Send Events → All Events**, **Test Connection**, **Release**, then **Add New Sync**.

> 📺 [Create the Amplitude Event Streaming destination](https://app.arcade.software/share/NeCcl6dtC7DQdjOjue28)

**Common mistakes:** pointing the destination at the wrong `ingest_url` or omitting the `Bearer ` prefix on `ingest_secret` (401); `session_id = -1` briefly on first load (normal, resolves in seconds, Autoplay falls back to `device_id`); forgetting the Freemarker template (drops clicks/forms).

</Accordion>

<Accordion title="FullStory" icon="/images/recipes/fullstory/logo.png" iconType="image">

<Note>
  FullStory is the one provider with **no Python provider class and no frontend code change at all** — it's pure dashboard configuration, assuming FullStory is already installed and capturing (verify with `FS('getSession')`). Requires an **Enterprise/Advanced plan with the "Anywhere: Activation" add-on** and Admin/Architect role. Full reference: [FullStory how-to-setup](/recipes/fullstory/how-to-setup) and the [activity-fullstory agent skill](/get-started/agent-skills/activity-fullstory).
</Note>

**🧑 HUMAN — get the Autoplay ingest endpoint URL and Bearer token, then create a Stream (Settings → Anywhere → Activation → Create Stream)**

There's no `onboard_product(...)` call for FullStory — get the ingest URL and token from the Autoplay team or dashboard (see the linked how-to-setup doc above) before configuring the Stream below.

- Destination: HTTP Endpoint, `POST`, URL = your Autoplay ingest endpoint (from Autoplay onboarding), Auth = Bearer token.
- Trigger: event **Element Clicked**, no filters, frequency **On every event** (not "Once per session").
- Switch to JSON field mapping and paste:

```json
{
  "target_text": ["var", "event.0.target_text"],
  "element_name": ["var", "event.0.element_name"],
  "page_url": ["var", "event.0.url"],
  "timestamp": ["var", "event.0.event_time"],
  "timestamp_unix": ["toUnixTimestamp", ["var", "event.0.event_time"]],
  "session_replay_url": ["var", "event.0.app_url_event"],
  "user_id": ["var", "event.0.user_id"],
  "user_email": ["var", "event.0.user_email"],
  "session_id": ["concat", ["var", "event.0.device_id"], "%3A", ["var", "event.0.session_id"]]
}
```

`session_id` here is a **concatenation** of `device_id` + `%3A` + FullStory's own session id — structurally different from PostHog's/Amplitude's native session ids, but that's fine; it's what everything downstream keys on.

- Click **Send Test**, confirm `200 OK`, **Save**.
- Allowlist the connector's IP on the Autoplay side if required: US `8.35.195.0/29`, EU `34.89.210.80/29`.

FullStory retries failed deliveries up to 30 times over 5 hours, so a brief outage on the connector side self-heals.

</Accordion>

</AccordionGroup>

### Verify Path 1 before moving on

**🤖 AGENT**

The connector is **pull-based**, not streaming — click around the app as an identified user, then fetch that user's activity with `mcp_url` / `mcp_key` from registration:

```bash
curl "YOUR_MCP_URL/users/YOUR_PRODUCT_ID/YOUR_USER_ID/live-activity?limit=10" \
  -H "Authorization: Bearer YOUR_MCP_KEY"
```

A `200` with a populated `actions` array means events are flowing — this is the exact same data the agent reads over MCP in Path 2. An empty array usually means the frontend identify call hasn't fired yet, not a connector problem.

---

## Path 2 — AI Support Agent

### What's shared across every platform

**🤖 AGENT**

There are two distinct mechanisms in this codebase — pick per platform, they aren't interchangeable:

- **MCP pull (current, recommended):** the platform calls Autoplay's MCP server mid-conversation to pull live activity on demand. Today this is fully built out for **Intercom** only.
- **Push (older pattern):** a Python backend consumes the SSE stream from Path 1 and pushes context into the platform (internal notes, table rows, custom fields) via a `BaseChatbotWriter` subclass. This is what the other platforms' skills describe.

The MCP server, regardless of platform: endpoint `https://mcp.autoplay.ai/mcp` (no trailing slash — some clients are strict about it), Streamable HTTP transport, `Authorization: Bearer YOUR_MCP_KEY`. One tool, `get_live_user_activity(product_id, user_id, limit?)`, returns `{product_id, user_id, count, as_of, actions[]}` from a 24h/50-action rolling store. `user_id` must be byte-identical to whatever the activity provider identified the user with in Path 1 — this is the single most common failure across every platform ("no recent activity" instead of an error).

<AccordionGroup>

<Accordion title="Intercom (Fin) — MCP, recommended default" icon="/images/recipes/intercom/logo.png" iconType="image">

<Note>Requires a **US-hosted** Intercom workspace — MCP connectors aren't available on EU/AU hosting. Full step-by-step reference with screenshots: [Intercom MCP recipe](/recipes/intercom-tutorial/step-1-connect-real-time-events).</Note>

**🧑 HUMAN — add the MCP connector**

**Settings → Integrations → Data connectors → Custom MCP.** Name it `Autoplay live activity`, URL `https://mcp.autoplay.ai/mcp`. Click **+ New**, check **Get Live User Activity**, add it.

**🧑 HUMAN — configure the tool (Draft → Edit → API tab)**

- `product_id` → **Custom value**, your product id (set the fallback too).
- `user_id` → **Use an attribute** → the **User ID** people attribute (not Contact ID, not email).
- `limit` → **Let Fin decide**.
- **Authentication → New token**: Type `Text`, value = your `mcp_key` (no "Bearer" typed manually), prefix `Bearer`, header key `Authorization`.

**Fin tab:** write a prompt telling Fin when to call this — "user asks what they were just doing," "stuck in a flow," mentions an error. Explicitly note it should *not* fire for billing/account/general how-to questions. Check **"Enable Fin to use this connector directly."**

**🤖 AGENT — wire Messenger identity (JWT)**

```javascript
// server-side only — never ship this secret to the browser
const token = jwt.sign(
  { user_id: req.user.id, email: req.user.email, exp: Math.floor(Date.now() / 1000) + 3600 },
  process.env.INTERCOM_IDENTITY_SECRET,
  { algorithm: "HS256" }
);
```

```javascript
window.Intercom("boot", { app_id: "YOUR_INTERCOM_APP_ID", intercom_user_jwt: token });
// do NOT also set user_id/email directly on boot — the JWT is the sole identity source
```

`user_id` claim in the JWT must equal the id used in Path 1's identify call. Get the Unified Secret from **Settings → Channels → Messenger → Security**; turn on enforcement there only after testing the token at jwt.io.

**🧑 HUMAN — test and go live:** the tool's **Test** tab with a real `product_id`/`user_id` should return `200` with populated actions. Click **Set live**. Full loop check: log in as a test user, click around, open Messenger as that user, ask Fin "what have I been doing?"

For the older internal-notes push pattern instead of MCP (uses `conv_map` + webhooks + `POST /conversations/{id}/parts`), see [chatbot-intercom skill](/get-started/agent-skills/chatbot-intercom).

</Accordion>

<Accordion title="Ada" icon="/images/recipes/ada/logo.png" iconType="image">

No MCP — push-based via `metaFields`. Backend consumes the SSE stream, keeps a Redis-backed `GET /context/{session_id}` endpoint (`build_copilot_app` from `autoplay_sdk.api` does this out of the box). Frontend fetches that context and passes it into `adaEmbed.start({ metaFields, ... })`.

**🧑 HUMAN — create 4 String variables in Build → Variables:** `session_id`, `current_page`, `recent_actions`, `session_summary` (no spaces/periods/emojis, case-sensitive).

**🤖 AGENT**

```html
<script id="__ada" data-handle="YOUR-BOT-HANDLE" data-lazy src="https://static.ada.support/embed2.js"></script>
```

<Warning>
  `window.adaEmbed` exists as soon as the script tag loads (because of `data-lazy`) — **before** `.start()` runs. Calling `setMetaFields`/`toggle` before `adaReadyCallback` fires silently no-ops. Track readiness with your own flag.
</Warning>

Full details including the SPA `pushState` gotcha and Ada lifecycle events: [Ada recipe](/recipes/ada/step-1-connect-real-time-events).

</Accordion>

<Accordion title="Botpress" icon="/images/recipes/botpress/logo.png" iconType="image">

Push-based via **Botpress Tables**, no MCP. Create two tables in Botpress Studio: `AutoPlayEventsTable` (`title, description, canonical_url, user_id, product_id, session_id`) and `AutoPlayEventsSummaryTable` (`summary, session_id`) — `session_id` is the row key, always filter by it. A `StoreEventsData` code node (webhook-triggered) writes rows; a `FetchEventsData` code node (runs before the Autonomous Agent on every message) reads the last 20 rows + latest summary into `workflow.agentContext`, which the Autonomous Agent's system prompt must reference via `{{workflow.agentContext}}`. Details: [chatbot-botpress skill](/get-started/agent-skills/chatbot-botpress).

</Accordion>

<Accordion title="Dify, Crisp, Landbot, Tidio">

<Warning>
  These are **documentation stubs today**, not complete tutorials — don't promise the customer a finished integration. Each skill ([Dify](/get-started/agent-skills/chatbot-dify) · [Crisp](/get-started/agent-skills/chatbot-crisp) · [Landbot](/get-started/agent-skills/chatbot-landbot) · [Tidio](/get-started/agent-skills/chatbot-tidio)) only describes the generic pattern (link a platform conversation id to Autoplay's `session_id` via `conv_map` + `on_session_linked`, same shared building block every push integration uses) without platform-specific API calls or UI steps. If the customer picks one of these, read the linked skill first, then tell them explicitly that you'll be implementing the generic `BaseChatbotWriter` pattern by hand against that platform's own API docs, not following an existing verified recipe — and flag it to the Autoplay team via [Discord](https://discord.gg/jCbR2tQA5) so the gap gets prioritized.
</Warning>

</Accordion>

<Accordion title="Zendesk, Rasa, Inkeep, Maven — not built yet">

No integration exists for these. If the customer needs one, point them to Discord rather than attempting to build it from scratch here.

</Accordion>

</AccordionGroup>

---

## Path 3 — Visual User Tours

### The one mechanism behind all seven tools

**🤖 AGENT**

<Note>
  Autoplay does **not** call any tour vendor's API directly — there's no server-to-server integration per vendor, no vendor credentials stored in Autoplay. Instead, Autoplay's [proactive triggers](/sdk/proactive-triggers) decide *when/what* to say, and emit a session-scoped SSE event; **the customer's own frontend** listens for it and calls the vendor's client-side SDK. "Setting up this pillar" means: wire this listener once, then hand it a `flow_id` per vendor.
</Note>

**🤖 AGENT — one shared listener, regardless of vendor**

```javascript
const es = new EventSource('YOUR_SERVER_PROXY/stream');  // proxy the connector's SSE stream server-side; keep ingest_secret/mcp_key off the client
es.addEventListener('usertour_trigger', (event) => {
  const payload = JSON.parse(event.data); // { type, product_id, session_id, flow_id }
  if (payload.session_id !== currentSessionId) return; // must match the current activity-provider session
  // call the vendor's SDK here — see the table below for the exact one-liner
});
```

**🧑 HUMAN — per vendor, before the listener works:** they must already have that vendor's own tracking snippet installed (standard vendor onboarding, not an Autoplay step), and must have already built and published the specific tour/flow/guide in that vendor's own dashboard, then copied its id into wherever `flow_id` is set when the trigger fires.

| Tool | Identify call | Where the flow/tour/guide id lives | One-line trigger call |
|---|---|---|---|
| [Userpilot](/recipes/userpilot/how-to-setup) | `userpilot.identify(userId, {...})` | "Content ID" in the flow's edit URL | `userpilot.trigger(payload.flow_id)` |
| [Chameleon](/recipes/chameleon/how-to-setup) | `chmln.identify(userId, {...})` | "Tour ID" shown under the tour name | `chmln.show(payload.flow_id)` |
| [Userflow](/recipes/userflow/how-to-setup) | `userflow.identify(userId, {...})` | "Flow ID" in the flow's URL | `userflow.start(payload.flow_id)` |
| [Pendo](/recipes/pendo/how-to-setup) | `pendo.initialize({visitor:{id:userId}, account:{id:...}})` — identify folded into init, needs an account id unlike the others | "Guide ID" in the guide's edit URL | `pendo.showGuideById(payload.flow_id)` |
| [Usertour](/recipes/usertour/how-to-setup) | `await usertour.identify(userId, {...})` (async) | "Flow ID" in the flow's edit URL | `usertour.start(payload.flow_id)` |
| [UserGuiding](/recipes/userguiding/how-to-setup) | `window.userGuiding.identify(userId, {...})` | "Guide ID" in the guide's edit URL | `window.userGuiding.previewGuide(payload.flow_id)` |
| [Told](/recipes/told/how-to-setup) | `told.identify(userId, {...})` | "Tour ID" in the tour's edit URL | `told.startTour(payload.flow_id)` |

<Note>
  The SSE event is always named `usertour_trigger` even when the vendor isn't the one literally called "Usertour" — don't let that naming coincidence confuse the wiring.
</Note>

**If the customer uses a tour tool not in this table:** the mechanism only needs a client-side "launch this flow by id" SDK method, so the same listener pattern works — there's just no existing recipe page to link them to. Build the vendor call by hand from that vendor's own docs and consider skipping this pillar for now if it's not a priority.

**No tour tool at all?** Skip this pillar — nothing else in the setup depends on it.

To actually make a trigger fire (rather than just wiring the listener), see [Proactive triggers](/sdk/proactive-triggers) and [Authoring triggers](/sdk/proactive-triggers-authoring) — three built-ins exist (`canonical_url_ping_pong`, `user_page_dwell`, `section_playbook_match`); only the first is on by default.

---

## Final step — verify the whole stack

**🤖 AGENT** (customer triggers real activity)

1. **Path 1:** `curl "YOUR_MCP_URL/users/YOUR_PRODUCT_ID/YOUR_USER_ID/live-activity" -H "Authorization: Bearer YOUR_MCP_KEY"` while the customer clicks around — the `actions` array should populate within seconds.
2. **Path 2 (Intercom/MCP):** run the connector's Test tab with a real `product_id`/`user_id`, then ask Fin a context-dependent question as that same logged-in user in the actual Messenger.
3. **Path 2 (push platforms):** trigger the platform's webhook (e.g. open a new conversation) and confirm a note/row appears within ~10s.
4. **Path 3:** manually fire (or wait for) a proactive trigger and confirm the vendor's tour actually launches in the browser.

---

## Reference

<CardGroup cols={2}>
  <Card title="Quickstart (human-facing)" icon="rocket" href="/quickstart">
    The same three pillars, click-through Mintlify format
  </Card>
  <Card title="Agent skills" icon="wand-magic-sparkles" href="/get-started/agent-skills">
    Per-provider Cursor/Claude skills this script installs
  </Card>
  <Card title="MCP server" icon="plug" href="/mcp/server">
    Full tool schema and auth details for get_live_user_activity
  </Card>
  <Card title="Proactive triggers" icon="bolt" href="/sdk/proactive-triggers">
    The mechanism that decides when Path 2/3 delivery fires
  </Card>
  <Card title="Identity" icon="fingerprint" href="/activity/identity">
    The cross-pillar user_id matching rule and how to debug it
  </Card>
  <Card title="Use cases" icon="target" href="/who-we-are/use-cases">
    Outcome framing if the customer asks "what's this for"
  </Card>
</CardGroup>
