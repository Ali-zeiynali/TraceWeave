# Configuration reference

TraceWeave reads `.env` through Pydantic Settings with the `TRACEWEAVE_` prefix and reads model routes from `providers.toml`.

## Storage

```dotenv
TRACEWEAVE_DATA_DIR=.traceweave
```

## Search

```dotenv
TRACEWEAVE_SEARCH_BACKEND=auto
TRACEWEAVE_SEARXNG_URL=http://127.0.0.1:8080
TRACEWEAVE_SEARCH_TIMEOUT_SECONDS=20
```

Values for backend: `auto`, `searxng`, `ddgs`.

## Fetch / traversal

```dotenv
TRACEWEAVE_FETCH_TIMEOUT_SECONDS=20
TRACEWEAVE_FETCH_MAX_BYTES=3000000
TRACEWEAVE_FETCH_CONCURRENCY=4
TRACEWEAVE_USER_AGENT=TraceWeave/0.3
TRACEWEAVE_RESPECT_ROBOTS=true
TRACEWEAVE_FRONTIER_ENABLED=true
TRACEWEAVE_FRONTIER_MIN_SCORE=0.16
TRACEWEAVE_FRONTIER_PER_DOMAIN_LIMIT=8
TRACEWEAVE_SITEMAP_ENABLED=true
```

For an 8 GB VPS, begin with HTTP concurrency 4–8 rather than immediately maximizing it.

## Optional browser

```dotenv
TRACEWEAVE_BROWSER_FALLBACK=false
TRACEWEAVE_BROWSER_MIN_TEXT_CHARS=500
```

Install the `browser` extra before enabling.

## Evidence

```dotenv
TRACEWEAVE_TRIAGE_ENABLED=true
TRACEWEAVE_CLAIMS_ENABLED=true
TRACEWEAVE_CLAIMS_MAX_SOURCES_PER_ROUND=8
TRACEWEAVE_CLAIM_MIN_RELEVANCE=55
```

`CLAIMS_MAX_SOURCES_PER_ROUND` is an important free-tier control: it bounds expensive extraction calls even when collection finds many pages.

## Router

```dotenv
TRACEWEAVE_PROVIDER_CONFIG=providers.toml
TRACEWEAVE_LLM_TIMEOUT_SECONDS=75
TRACEWEAVE_LLM_TEMPERATURE=0.15
TRACEWEAVE_ROUTER_MAX_ATTEMPTS=6
TRACEWEAVE_ROUTER_HEALTH_TTL_SECONDS=900
```

`ROUTER_MAX_ATTEMPTS` is attempts per model task, not per research run. `ROUTER_HEALTH_TTL_SECONDS` controls how long old success/failure/latency statistics influence ranking; an active cooldown remains absolute until its own expiry.

Stage-1 compatibility:

```dotenv
TRACEWEAVE_API_BASE=
TRACEWEAVE_API_KEY=
TRACEWEAVE_MODEL=
```

These produce one legacy route only when no provider routes are configured.

## Shell

```dotenv
TRACEWEAVE_SHELL_ENABLED=false
TRACEWEAVE_SHELL_TIMEOUT_SECONDS=30
TRACEWEAVE_SHELL_MAX_OUTPUT_CHARS=20000
```

The TUI session can enable/disable shell independently. Shell is local and unsandboxed.

## Provider TOML schema

```toml
[[providers]]
id = "example"
driver = "openai_compat"          # or litellm
base_url = "https://api.example/v1"
enabled = true
headers = { "X-Custom" = "value" }

[[providers.credentials]]
id = "key-a"
token_env = "EXAMPLE_KEY_A"
enabled = true

[[providers.credentials]]
id = "key-b"
token_env = "EXAMPLE_KEY_B"

[[providers.models]]
id = "fast"
name = "provider-model-id"
tasks = ["triage", "claim_extraction"]
priority = 20
weight = 1.5
capabilities = ["json"]

[[providers.models]]
id = "reasoner"
name = "provider-reasoning-id"
tasks = ["planning", "replanning", "synthesis"]
priority = 10
weight = 1.0
credentials = ["key-b"]
```

### Semantics

- `id`: stable local id used in health state/logs. Do not put the secret value here.
- `token_env`: environment variable containing the raw token.
- `tasks`: allowed TraceWeave task classes. `['*']` accepts all.
- `priority`: lower is preferred before runtime-health adjustments.
- `weight`: larger makes a healthy route relatively more attractive.
- `credentials`: optional allow-list of credential ids for a model.
- `capabilities`: descriptive metadata/future routing input; current task routing primarily uses `tasks`.
- extra model keys can be passed to the driver-specific `request` or `litellm` maps.

For an OpenAI-compatible endpoint:

```toml
request = { max_tokens = 4096 }
```

For LiteLLM:

```toml
litellm = { max_tokens = 4096 }
```

Check current provider/model identifiers in the provider or LiteLLM official documentation because catalogs change.
