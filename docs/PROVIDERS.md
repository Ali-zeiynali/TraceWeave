# Provider / Model Router — v1.0.2

## Built-in provider presets

The built-in presets are activated only when their environment key exists. No token is hard-coded or written to SQLite/catalog files.

### Environment convention

For every built-in provider:

```dotenv
PROVIDER_API_KEY=token-one
PROVIDER_API_KEY_2=token-two
PROVIDER_API_KEY_3=token-three
PROVIDER_API_KEY_4=token-four
PROVIDER_API_KEY_5=token-five
```

`PROVIDER_API_KEY_1` is accepted in place of the unnumbered first key.

Supported preset prefixes:

- `AGENTROUTER`
- `SEEKROUTER`
- `ZENMUX`
- `OPENROUTER`
- `MISTRAL`
- `GEMINI`
- `GROQ`
- `CEREBRAS`
- `SAMBANOVA`
- `CLOUDFLARE` (also requires `CLOUDFLARE_ACCOUNT_ID`)
- `NVIDIA_TEXT`, `NVIDIA_VISION` (or one shared `NVIDIA_API_KEY`)
- `NARAROUTER`
- `AIGATE` (`AIGATEAPI_KEY` is also accepted for compatibility)

Each also accepts `PROVIDER_BASE_URL` for endpoint override.

## Current preset strategy

### AgentRouter
Bootstrap strong routes include currently documented GPT/Kimi/GLM examples, then `/models` is discovered per credential. This provider is treated as opportunistic/credit-backed, not assumed free.

Default base: `https://co.agentrouter.org/v1` (overrideable).

### SeekRouter
Models are discovered from `/models` per credential because available models can vary. The currently documented base may use HTTP; TraceWeave emits a warning and supports `SEEKROUTER_BASE_URL` override. Prefer HTTPS whenever the provider/account offers it.

### ZenMux
Static zero-priced candidates include current GLM free variants; dynamic catalog rows are filtered to zero-priced/Free identifiers. A zero-priced model is not the same thing as API entitlement: the supplied ZenMux account must actually have API access.

### OpenRouter
`openrouter/free` is always available as a preset candidate when a key is configured. The dynamic Models API is queried and only zero-priced/`:free` chat models are attached. Free-model availability is intentionally dynamic.

### Mistral
`mistral-small-latest` bootstraps the route; `/models` is queried per token because Free-mode organization access and model availability can vary. TraceWeave does not pretend every public Mistral model is included in every free account.

### Gemini
Current curated Flash/Flash-Lite routes are used through Google's OpenAI-compatible endpoint. Strong planning/synthesis prefers newer Flash; triage/entity extraction prefers faster Flash-Lite routes.

### Groq
Current curated routes separate strong GPT-OSS 120B from faster GPT-OSS 20B/Qwen workers. The router uses the normal Groq OpenAI-compatible endpoint.

### Cerebras / SambaNova
Both use their OpenAI-compatible endpoints, free-tier bootstrap models, per-token health and dynamic catalogs. Catalog/model
availability remains credential scoped.

### Cloudflare Workers AI
The base URL is assembled from `CLOUDFLARE_ACCOUNT_ID`. Presets include only `@cf/*` Workers AI models. Third-party AI
Gateway routes are not added because they can use Unified Billing.

Three account/token pairs are supported: the unnumbered pair and `_2`/`_3`. Each account ID is bound to its matching token
for inference and catalog discovery. Cloudflare Browser Rendering rotates the same three pairs independently of Workers AI.

### NVIDIA NIM

`NVIDIA_TEXT_API_KEY` and `NVIDIA_VISION_API_KEY` create separate task pools against
`https://integrate.api.nvidia.com/v1`. If only `NVIDIA_API_KEY` or one role key is present, TraceWeave reuses it for both
roles. `/models` remains credential scoped and vision-looking rows are excluded from the text pool.

### NaraRouter

NaraRouter uses `https://router.bynara.id/v1`. Its `/models` response reflects each token's entitlement, so TraceWeave does
not assume a global model list. Published free limits are quotas, not a guarantee of permanent availability.

### AIGate

AIGate uses `https://api.aigate.shop/v1` by default and discovers its catalog per credential. It receives a lower routing
priority and a provider-level network circuit breaker because it is an operator-provided gateway with less stable
availability. `AIGATE_BASE_URL` can override the endpoint.

## Routing score

The candidate pool is first filtered by requested task and cooldown state. Remaining candidates are ranked by configured task priority, historical failure ratio, latency EMA, and route weight.

Priority is intentional: a fast classifier should not silently replace the strong planning model merely because it has 100 ms lower latency.

## Failure scopes

| Failure | Scope | Example |
|---|---|---|
| 401 | credential | invalid/expired token |
| 402 | credential | credit/quota exhausted |
| 429 | credential | token/account rate limit |
| 400/403/404/422 model/request | deployment | token may still work with another model |
| timeout/network/5xx | deployment | route-specific availability problem |
| refusal | task | model may still be useful for other research tasks |
| invalid JSON | task | do not discard model for free-text synthesis |
| refusal/task evasion | task | retry another deployment even when HTTP status was 200 |

For credential failures, only that token is cooled. Other tokens on the same provider remain candidates.

Repeated network failures also open a short provider-level circuit so a gateway with many models cannot consume every retry.
Intent/triage calls are capped at 25 seconds, planning/verification at 45 seconds, and synthesis/vision retain the configured
global timeout.

## Dynamic TTL

If `Retry-After` or recognized rate-limit reset headers exist, their delay is preferred. Otherwise TraceWeave uses capped exponential backoff based on failure type.

Observed health becomes stale after `TRACEWEAVE_ROUTER_HEALTH_TTL_SECONDS`, so old latency/failure history stops dominating current routing.

## Model catalog TTL

Dynamic `/models` results are stored per provider+credential under `.traceweave/catalog/models.json`. Catalog TTL is controlled by `TRACEWEAVE_PROVIDER_CATALOG_TTL_SECONDS`.

A failed catalog refresh receives its own provider+credential retry schedule (30 s exponential, capped at 30 min) and does not kill curated fallback routes. An async refresh lock prevents concurrent model calls from stampeding a flaky endpoint.

Catalog refresh is not placed on the call latency path while at least one usable route is already known. Use `traceweave
providers --sync` for an explicit refresh.

## Usage telemetry

Every attempt records provider, credential slot, model, task, success/failure class, HTTP status, latency and provider-returned
usage counts. Raw keys and prompt/response bodies are not stored. The TUI `/dashboard` and SQLite aggregation show requests,
failures, prompt/completion/total tokens, average latency and last-use time.

## Explicit override

Copy `providers.example.toml` to `providers.toml` only when you want to override a built-in provider or add a custom route. Explicit provider IDs replace the same built-in ID.

## Official references used for current presets

- Groq models: https://console.groq.com/docs/models
- Gemini models: https://ai.google.dev/gemini-api/docs/models
- Mistral usage/limits: https://docs.mistral.ai/admin/billing-usage/usage-limits
- OpenRouter free router: https://openrouter.ai/docs/guides/routing/routers/free-router
- OpenRouter Models API: https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties
- NVIDIA OpenAI-compatible VLM API: https://docs.nvidia.com/nim/vision-language-models/latest/api-reference.html
- Cloudflare Browser Rendering markdown: https://developers.cloudflare.com/browser-run/quick-actions/markdown-endpoint/
- NaraRouter documentation: https://router.bynara.id/docs

Provider catalogs change; the dynamic-catalog design exists specifically so TraceWeave is not tied forever to this list.

`TRACEWEAVE_ZERO_COST_ONLY=true` blocks routes explicitly marked paid. It cannot inspect the billing plan attached to an API
key; operators must keep paid upgrades/billing disabled in provider dashboards.
