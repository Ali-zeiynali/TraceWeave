# TraceWeave v0.5 — Usage Guide

## 1. Install

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .\.venv\Scripts\Activate.ps1
pip install -e '.[stage4]'
cp .env.example .env           # Windows: Copy-Item .env.example .env
```

Add only the API keys you actually have. TraceWeave also works without an LLM route: deterministic planning and collection remain available, but model triage/claim extraction/synthesis are reduced.

## 2. First launch

```bash
traceweave
```

The landing screen intentionally contains no empty plan/source/log panels. It shows:

- centered research input
- current working-folder name
- currently selected planning provider/model (or deterministic/catalog discovery)
- resumable run hint when a session has one
- a randomized tip

Type a topic and press Enter. The research workspace is mounted visually only after a run starts or you explicitly resume one.

## 3. Research controls

```text
/research TOPIC
/angle TEXT
/mode quick|standard|deep|overnight
/rounds N
/depth 0..5
/budget N
/language CODE
/pause
/resume [RUN_ID]
```

Modes provide defaults, but explicit `/rounds`, `/depth`, and `/budget` override them for the next run.

- `quick`: one round; no deep recursive traversal.
- `standard`: two rounds, light specialist/archive work, shallow frontier.
- `deep`: multiple plan/search/re-plan rounds, academic/code sources, archives, citation snowballing, and best-first recursive traversal.

- `overnight`: ten rounds, depth five, a 300-page frontier and a durable 24-hour deadline.

## 4. Inspect durable research state

```text
/runs
/sources [RUN_ID]
/claims [RUN_ID]
/frontier [RUN_ID]
/archives [RUN_ID]
/citations [RUN_ID]
/entities [RUN_ID]
/timeline [RUN_ID]
/graph [RUN_ID]
/router
```

CLI equivalents include:

```bash
traceweave runs
traceweave show RUN_ID
traceweave claims RUN_ID
traceweave archives RUN_ID
traceweave entities RUN_ID
traceweave timeline RUN_ID
traceweave router-log
```

## 5. Providers

No `providers.toml` is required for the built-in provider mesh. Put up to five tokens/provider in `.env`, then:

```text
/providers
/providers sync
/providers reload
```

or:

```bash
traceweave providers --sync --task planning
```

Catalog sync is credential-scoped. If token-1 can see model A and token-2 cannot, model A is only attached to token-1. Catalog refresh obeys a cache TTL; failed `/models` calls get a separate provider+token exponential retry window.

Runtime request health is separate:

- 401/402/429 → token/credential cooldown
- model-specific permission/request failure → token+model cooldown
- refusal/invalid structured output → token+model+task cooldown
- timeout/5xx/network → deployment cooldown

`Retry-After` / rate-limit reset headers win over computed backoff when present.

## 6. Sessions

```text
/session list
/session new NAME
/session switch ID
/session rename NAME
```

A session stores operator state such as angle, mode, language, active run, and local-shell setting. Runs and research evidence remain separately durable in SQLite.

## 7. Local shell

Disabled by default:

```text
/shell status
/shell enable
!git status
/shell disable
```

This is a local operator convenience, not an agent tool. Fetched web content and model responses cannot trigger it. Commands run with the OS permissions of the TraceWeave process, so keep it disabled unless needed.

## 8. Exports

```text
/export md
/export json
/export mermaid
/export evidence
```

or:

```bash
traceweave export RUN_ID --format md
traceweave export RUN_ID --format json
traceweave export RUN_ID --format mermaid
traceweave export RUN_ID --format evidence
```

JSON contains queries, provider-usage telemetry, sources/discoveries, claims, frontier, archive captures,
citations, entities, relationships, timeline events, artifacts, observations, research edges, and event log.
Mermaid includes the search trail and a bounded entity/relationship overlay.

## 9. Local media analysis

    pip install -e '.[media]'

Install Tesseract language packs on the host for OCR. The larger optional OpenCV layer is installed with
`.[media-advanced]`. Deterministic metadata/OCR/hash/quality analysis runs before opt-in remote vision. Important
public OCR/Vision observations are fed back into re-planning as traceable follow-up queries and into synthesis as
explicitly uncorroborated visual leads; raw observations remain in SQLite and `findings.json`.

For repeatable end-to-end checks, run `python scripts/benchmark_agent.py --help`. The harness invokes the public
prompt-first CLI and records latency, query-language coverage, citations, graph edges, observations, token usage,
and provider failures without reading or printing key values.

## 10. Stage 4 configuration

Useful `.env` knobs:

```dotenv
TRACEWEAVE_ARCHIVES_ENABLED=true
TRACEWEAVE_WAYBACK_ENABLED=true
TRACEWEAVE_COMMONCRAWL_ENABLED=true
TRACEWEAVE_ACADEMIC_ENABLED=true
TRACEWEAVE_GITHUB_ENABLED=true
TRACEWEAVE_PDF_ENABLED=true
TRACEWEAVE_ARCHIVE_SOURCES_PER_ROUND=4
TRACEWEAVE_ARCHIVE_CAPTURES_PER_SOURCE=3
TRACEWEAVE_SPECIALIST_QUERIES_PER_ROUND=3
TRACEWEAVE_SPECIALIST_RESULTS_PER_QUERY=5
TRACEWEAVE_PDF_MAX_BYTES=20000000
TRACEWEAVE_GITHUB_TOKEN=
TRACEWEAVE_OPENALEX_MAILTO=
```

For a small VPS, increase source budgets slowly. Browser rendering is the expensive part; ordinary HTTP, archive APIs, and academic APIs are much lighter.

## 10. Troubleshooting

### No model shown on landing
Run `/providers sync` or `traceweave providers --sync`. A router with only dynamic models may display `deterministic / catalog discovery` until its first successful catalog sync.

### One token is rate limited
Do nothing manually unless all routes are exhausted. TraceWeave cools that credential and tries another credential/model/provider.

### Research paused/crashed
Use `/resume` or `traceweave resume RUN_ID`. Search/source/provenance state is committed incrementally.

### SeekRouter warning
The built-in preset follows the provider's documented base URL, which may be HTTP. If your account/provider gives you HTTPS, set `SEEKROUTER_BASE_URL` to that HTTPS endpoint.

### ZenMux key but free model does not run
A zero-priced model does not imply that every ZenMux subscription can call the API. The router will catalog/probe only what the supplied API credential can actually access.

### PDFs fail
Install Stage 4 extras:

```bash
pip install -e '.[stage4]'
```

### JS-only page
Install full extras and enable browser fallback intentionally:

```bash
pip install -e '.[full]'
crawl4ai-setup
```

```dotenv
TRACEWEAVE_BROWSER_FALLBACK=true
```
