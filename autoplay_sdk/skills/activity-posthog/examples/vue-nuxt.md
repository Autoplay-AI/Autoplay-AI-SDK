# Example: Nuxt 3 + Vue 3 + TypeScript

Anchored on the `vue-nuxt-with-posthog` fixture. PostHog init lives in a
client-only Nuxt plugin (`plugins/posthog.client.ts`) and is provided as
`$posthog`; `identify` is called in `app.vue` `onMounted`. The patch adds
`product_id` to identify (via runtime config) and a `NUXT_PUBLIC_*` env var.

## `nuxt.config.ts` — expose the product id in runtimeConfig

BEFORE:
```ts
export default defineNuxtConfig({
  compatibilityDate: "2024-07-01",
  runtimeConfig: {
    public: {
      posthogPublicKey: process.env.NUXT_PUBLIC_POSTHOG_KEY,
      posthogHost:
        process.env.NUXT_PUBLIC_POSTHOG_HOST || "https://us.i.posthog.com",
    },
  },
});
```

AFTER (add one public key):
```ts
export default defineNuxtConfig({
  compatibilityDate: "2024-07-01",
  runtimeConfig: {
    public: {
      posthogPublicKey: process.env.NUXT_PUBLIC_POSTHOG_KEY,
      posthogHost:
        process.env.NUXT_PUBLIC_POSTHOG_HOST || "https://us.i.posthog.com",
      autoplayProductId: process.env.NUXT_PUBLIC_AUTOPLAY_PRODUCT_ID,
    },
  },
});
```

## `app.vue` — patch identify

BEFORE:
```vue
<script setup lang="ts">
import { onMounted } from "vue";

const user = { id: "user_123", email: "jane@acme.com" };

onMounted(() => {
  const { $posthog } = useNuxtApp();
  $posthog.identify(user.id, { email: user.email });
});
</script>
```

AFTER:
```vue
<script setup lang="ts">
import { onMounted } from "vue";

const user = { id: "user_123", email: "jane@acme.com" };

onMounted(() => {
  const { $posthog } = useNuxtApp();
  const config = useRuntimeConfig();
  $posthog.identify(user.id, {
    email: user.email,
    product_id: config.public.autoplayProductId,
  });
});
</script>
```

The plugin's `posthog.init` (`api_host: "https://us.i.posthog.com"`) is left
unchanged; Step 5b only confirms it matches `POSTHOG_HOST`.

## `.env` — add the product-id var

```
NUXT_PUBLIC_AUTOPLAY_PRODUCT_ID=12345
```

Show all diffs and confirm `[y/n]` before applying.
