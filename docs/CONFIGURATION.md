# Configuration Reference — v1.0.2

TraceWeave loads core settings through `pydantic-settings` and loads simple `.env` assignments into the process without
overwriting parent environment variables. This is required for unprefixed provider keys such as `GROQ_API_KEY`; secrets are
kept in memory and are not written to SQLite/catalog/health logs.

See `.env.example` for a complete copy/paste template.

## Core

| Variable | Default | Purpose |
|---|---:|---|
| `TRACEWEAVE_DATA_DIR` | `.traceweave` | durable state root |
| `TRACEWEAVE_SEARCH_BACKEND` | `auto` | `auto`, `searxng`, `ddgs` |
| `TRACEWEAVE_SEARXNG_URL` | local 8080 | self-hosted SearXNG |
| `TRACEWEAVE_FETCH_CONCURRENCY` | 4 | ordinary fetch concurrency |
| `TRACEWEAVE_RESPECT_ROBOTS` | true | live crawl robots policy |

## Frontier

`TRACEWEAVE_FRONTIER_ENABLED`, `TRACEWEAVE_FRONTIER_MIN_SCORE`, `TRACEWEAVE_FRONTIER_PER_DOMAIN_LIMIT`,
`TRACEWEAVE_SITEMAP_ENABLED`, `TRACEWEAVE_BROWSER_FALLBACK`, `TRACEWEAVE_BROWSER_BACKEND` (`auto`, `cloudflare`,
`local`), `TRACEWEAVE_BROWSER_MIN_TEXT_CHARS`, `TRACEWEAVE_FETCH_PER_HOST_DELAY_SECONDS`, and
`TRACEWEAVE_FETCH_RETRIES`.

## Evidence

`TRACEWEAVE_TRIAGE_ENABLED`, `TRACEWEAVE_CLAIMS_ENABLED`, `TRACEWEAVE_CLAIMS_MAX_SOURCES_PER_ROUND`, `TRACEWEAVE_CLAIM_MIN_RELEVANCE`.

## Stage 4

`TRACEWEAVE_ARCHIVES_ENABLED`, `TRACEWEAVE_WAYBACK_ENABLED`, `TRACEWEAVE_COMMONCRAWL_ENABLED`, `TRACEWEAVE_ACADEMIC_ENABLED`, `TRACEWEAVE_GITHUB_ENABLED`, `TRACEWEAVE_PDF_ENABLED`, `TRACEWEAVE_SPECIALIST_QUERIES_PER_ROUND`, `TRACEWEAVE_SPECIALIST_RESULTS_PER_QUERY`, `TRACEWEAVE_ARCHIVE_SOURCES_PER_ROUND`, `TRACEWEAVE_ARCHIVE_CAPTURES_PER_SOURCE`, `TRACEWEAVE_PDF_MAX_BYTES`, `TRACEWEAVE_GITHUB_TOKEN`, `TRACEWEAVE_OPENALEX_MAILTO`.

## Stage 5 foundation

`TRACEWEAVE_ENTITY_GRAPH_ENABLED` controls grounded entity/relationship/timeline curation.

## Durable runs, registries and media

`ResearchSpec` persists a wall-clock deadline, total model-attempt budget, separate remote-vision budget, retention mode and
Quick/Standard/Deep/Overnight mode. Registry/social/media settings include
`TRACEWEAVE_REGISTRY_SOURCES_ENABLED`, `TRACEWEAVE_PUBLIC_SOCIAL_ENABLED`, `TRACEWEAVE_BLUESKY_ENABLED`,
`TRACEWEAVE_TELEGRAM_PUBLIC_ENABLED`, `TRACEWEAVE_MEDIA_ENABLED`, `TRACEWEAVE_MEDIA_MAX_BYTES`, and
`TRACEWEAVE_REMOTE_VISION_ENABLED`.
Typed registry toggles are `TRACEWEAVE_CERTIFICATE_TRANSPARENCY_ENABLED`, `TRACEWEAVE_URLSCAN_ENABLED`,
`TRACEWEAVE_SEC_EDGAR_ENABLED`, `TRACEWEAVE_PEERINGDB_ENABLED`, and
`TRACEWEAVE_COMPANIES_HOUSE_ENABLED`. urlscan and Companies House also require their documented API keys;
SEC EDGAR requires a descriptive `SEC_USER_AGENT`.
`TRACEWEAVE_RESEARCH_QUERY_CONCURRENCY` controls independent query branches (default 3; fetch concurrency remains separate).
Official Instagram hashtag discovery additionally uses
`TRACEWEAVE_INSTAGRAM_OFFICIAL_ENABLED`, `INSTAGRAM_ACCESS_TOKEN`, and `INSTAGRAM_USER_ID`.

## Router

| Variable | Default |
|---|---:|
| `TRACEWEAVE_LLM_TIMEOUT_SECONDS` | 75 |
| `TRACEWEAVE_LLM_TEMPERATURE` | 0.15 |
| `TRACEWEAVE_ROUTER_MAX_ATTEMPTS` | 8 in example |
| `TRACEWEAVE_ROUTER_HEALTH_TTL_SECONDS` | 900 |
| `TRACEWEAVE_PROVIDER_CATALOG_TTL_SECONDS` | 21600 |
| `TRACEWEAVE_PROVIDER_CATALOG_AUTO_SYNC` | true |
| `TRACEWEAVE_PROVIDER_CONFIG` | `providers.toml` |
| `TRACEWEAVE_ZERO_COST_ONLY` | true |

## Provider keys

Use any subset of:

Every preset accepts the unnumbered key (or `_1`) plus `_2`, `_3`, `_4`, and `_5`. Prefixes are:
`AGENTROUTER`, `SEEKROUTER`, `ZENMUX`, `OPENROUTER`, `MISTRAL`, `GEMINI`, `GROQ`, `CEREBRAS`, `SAMBANOVA`,
`NARAROUTER`, `AIGATE`, `OPENAI`, `DEEPSEEK`, `XAI`, `TOGETHER`, and `FIREWORKS`. NVIDIA accepts
`NVIDIA_API_KEY` or separate `NVIDIA_TEXT_API_KEY` /
`NVIDIA_VISION_API_KEY` sets. Cloudflare accepts three matching `CLOUDFLARE_API_KEY[_2|_3]` and
`CLOUDFLARE_ACCOUNT_ID[_2|_3]` pairs.

Every provider also supports `<PREFIX>_BASE_URL` override.

## Shell

`TRACEWEAVE_SHELL_ENABLED=false`, `TRACEWEAVE_SHELL_TIMEOUT_SECONDS=30`, `TRACEWEAVE_SHELL_MAX_OUTPUT_CHARS=20000`.
