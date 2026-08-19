# Provider mesh and routing

## Design goal

Free-tier, promotional and small router endpoints are often inconsistent: one token may hit quota, one model may disappear, JSON behavior may degrade, or a model may refuse a specific task. TraceWeave therefore treats provider routing as a durable scheduling problem rather than a single fallback list.

## Routing unit

A deployment key is:

```text
provider_id : credential_id : model_id
```

Raw token values live only in environment variables. `providers.toml` references those environment-variable names.

## Failure scope

TraceWeave intentionally avoids hard provider-wide poisoning.

### Credential/token scope

Applied primarily to:

- HTTP 401 / 403 authentication failures
- HTTP 429 quota / rate-limit failures

A credential cooldown affects all models using that token because a rate/quota/auth problem is commonly token/account scoped. Other credentials belonging to the same provider remain eligible.

### Token + model deployment scope

Applied to:

- timeout / transient network failure
- 5xx upstream failure
- model/request incompatibility
- malformed endpoint response

This prevents one broken model deployment from disabling unrelated models or credentials.

### Token + model + task scope

Applied to:

- refusal-style output
- invalid JSON for structured tasks

A model that is poor for political `replanning`, for example, may still remain available for ordinary `triage`.

## Dynamic cooldown TTL

If the provider returns `Retry-After` or recognizable rate-reset headers, TraceWeave prefers that duration. Otherwise it uses bounded exponential backoff by failure class. Authentication failures have a longer cooldown; rate limits are shorter; timeouts/5xx are shorter still.

Historical success/failure/latency observations decay after `TRACEWEAVE_ROUTER_HEALTH_TTL_SECONDS`. An active absolute cooldown remains respected even when old scoring observations have decayed.

## Candidate score

Healthy candidates are filtered by task first, then ranked by:

- configured `priority`
- configured `weight`
- recent deployment failure ratio
- recent task failure ratio
- latency EMA

Explicit priority remains the strongest signal; runtime health adjusts it rather than completely replacing operator intent.

## Configuration

```toml
[[providers]]
id = "router-a"
driver = "openai_compat"
base_url = "https://router.example/v1"
enabled = true

[[providers.credentials]]
id = "token-a"
token_env = "ROUTER_TOKEN_A"

[[providers.credentials]]
id = "token-b"
token_env = "ROUTER_TOKEN_B"

[[providers.models]]
id = "cheap"
name = "cheap-model-id"
tasks = ["triage", "claim_extraction"]
priority = 20
weight = 1.5

[[providers.models]]
id = "reasoning"
name = "reasoning-model-id"
tasks = ["planning", "replanning", "synthesis"]
priority = 10
```

This produces four routes: two tokens × two models.

Restrict a model to selected credentials:

```toml
credentials = ["token-b"]
```

## Drivers

### `openai_compat`

Built into TraceWeave. Use it for endpoints implementing `POST /chat/completions`. This is the preferred path for small routers because it adds no heavy provider SDK.

### `litellm`

Optional:

```bash
pip install -e '.[providers]'
```

It allows TraceWeave to reuse LiteLLM's broad provider normalization while keeping TraceWeave's own credential/model/task health logic above it. Current LiteLLM documentation lists many providers and routing primitives; verify current provider prefixes/model ids in LiteLLM's official documentation before deployment.

Typical model-name shapes include:

```text
groq/<MODEL_ID>
gemini/<MODEL_ID>
anthropic/<MODEL_ID>
mistral/<MODEL_ID>
cerebras/<MODEL_ID>
openrouter/<MODEL_ID>
deepseek/<MODEL_ID>
```

Do not copy stale model ids from random lists; provider catalogs change quickly.

## Reload without restart

TUI:

```text
/providers reload
```

CLI:

```bash
traceweave providers --reload
```

Persisted health remains in SQLite because it is keyed by configured ids, not raw secrets.

## Task pools

Current task labels:

```text
planning
replanning
triage
claim_extraction
synthesis
general
```

A model can list `tasks=["*"]` to accept every task. Cheap workers should normally be restricted to triage/extraction while stronger long-context/reasoning models handle planning and synthesis.

## Debugging

```bash
traceweave providers
traceweave providers --task planning
traceweave router-log
```

The router log records route ids, outcome, failure class, HTTP status and latency. It never records the raw API token.
