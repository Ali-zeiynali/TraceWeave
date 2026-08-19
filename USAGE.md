# TraceWeave v0.3 Usage Guide

This guide covers installation, migration from v0.1, TUI/CLI use, provider routing, sessions, evidence, traversal, exports and common operational checks.

## 1. Upgrade an existing v0.1 checkout

Place `TraceWeave-patch-v0.1-to-v0.3.ps1` in the repository root and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\TraceWeave-patch-v0.1-to-v0.3.ps1
```

The patch preserves `.env`, `.git`, `.traceweave/` and an existing `providers.toml`; backs up files it replaces; applies the v0.3 overlay; installs dependencies unless disabled; initializes additive SQLite migrations; compiles the code; runs pytest and both smoke tests; then runs `traceweave doctor`.

Useful patch switches:

```powershell
# Files only
.\TraceWeave-patch-v0.1-to-v0.3.ps1 -SkipInstall -SkipTests

# Include LiteLLM provider support
.\TraceWeave-patch-v0.1-to-v0.3.ps1 -WithProviders

# Include Crawl4AI browser fallback
.\TraceWeave-patch-v0.1-to-v0.3.ps1 -WithBrowser

# Both optional extras
.\TraceWeave-patch-v0.1-to-v0.3.ps1 -WithFull
```

## 2. Fresh install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e .
cp -n .env.example .env
cp -n providers.example.toml providers.toml
traceweave doctor
traceweave
```

Optional broad provider support:

```bash
pip install -e '.[providers]'
```

Optional Crawl4AI:

```bash
pip install -e '.[browser]'
crawl4ai-setup
```

## 3. First TUI session

Run:

```bash
traceweave
```

Before a research request, TraceWeave intentionally shows only onboarding and the command input. The research workspace appears when there is meaningful content.

A simple start:

```text
/angle supply chain, partnerships and technical infrastructure
/mode deep
/depth 3
/budget 40
/research Example Company
```

You can also type a plain question without `/research`.

## 4. Iterative research behavior

A deep run does not generate one giant immutable plan. It repeatedly executes:

```text
PLAN
 → SEARCH
 → persist discovery
 → fetch/snapshot
 → triage/evidence
 → best-first link traversal
 → assess gaps/leads
 → RE-PLAN
 → targeted SEARCH
 → ...
```

Deep defaults to four rounds. The exact plan of every round is saved before execution, so resume continues unfinished work rather than inventing a new history.

## 5. TUI commands

### Research controls

```text
/research TOPIC
/angle TEXT
/mode quick|standard|deep
/rounds 1..10
/depth 0..5
/budget 0..500
/language LANGUAGE_OR_ALL
```

`depth` is a maximum recursive hop count. `budget` is the total number of recursive frontier pages allowed for the run; it does not include ordinary search-result discovery.

### Run/data inspection

```text
/runs
/resume [RUN_ID]
/pause
/sources [RUN_ID]
/claims [RUN_ID]
/frontier [RUN_ID]
/export [RUN_ID] [md|json|mermaid|evidence]
```

### Provider/router

```text
/providers
/providers reload
/router
/doctor
```

### Sessions

```text
/session list
/session new NAME
/session switch SESSION_ID
/session rename NAME
```

### Local shell

```text
/shell status
/shell enable
!git status
!python --version
/shell disable
```

Shell execution is local, disabled by default and **not a sandbox**.

### UI

```text
/clear
/help
/quit
```

The input has command suggestions, command history with Up/Down, and is cleared after execution. Textual's `Ctrl+P` command palette remains available. The old bottom footer/helper bar was removed.

## 6. CLI examples

Quick research:

```bash
traceweave research "Example Company" --mode quick
```

Deep research:

```bash
traceweave research "Example Company" \
  --mode deep \
  --angle "ownership, technology and historical changes" \
  --depth 3 \
  --frontier-budget 50 \
  --language all
```

Resume:

```bash
traceweave runs
traceweave resume RUN_ID
```

Inspect evidence:

```bash
traceweave show RUN_ID
traceweave claims RUN_ID
```

Router:

```bash
traceweave providers
traceweave providers --task planning
traceweave providers --reload
traceweave router-log --limit 100
```

Exports:

```bash
traceweave export RUN_ID --format md
traceweave export RUN_ID --format json
traceweave export RUN_ID --format mermaid
traceweave export RUN_ID --format evidence
```

## 7. Search configuration

Default:

```dotenv
TRACEWEAVE_SEARCH_BACKEND=auto
TRACEWEAVE_SEARXNG_URL=http://127.0.0.1:8080
```

`auto` tries SearXNG first, then DDGS. For a long-lived VPS, a self-hosted SearXNG instance is the preferred primary search interface.

Search-result provenance is stored **before fetch**. TraceWeave preserves the query, rank, engine, category, publication metadata and raw normalized search result even if the page later fails to download.

## 8. Provider mesh

Copy:

```bash
cp providers.example.toml providers.toml
```

Tokens belong in environment variables, not TOML:

```dotenv
ROUTER_A_TOKEN_1=...
ROUTER_A_TOKEN_2=...
GROQ_API_KEY_A=...
GEMINI_API_KEY_A=...
```

A candidate is:

```text
provider + credential/token + model
```

One provider can have many tokens and models. For example 3 tokens × 2 models may create six independently schedulable routes.

Failure isolation:

```text
401 / 403 / 429
  → token/credential cooldown

network / timeout / 5xx / model mismatch
  → token + model cooldown

refusal / invalid structured JSON
  → token + model + task cooldown
```

A failing token does not automatically disable other tokens belonging to that provider.

TTL behavior:

1. prefer provider `Retry-After` / recognized reset hints;
2. otherwise use failure-class-specific exponential backoff;
3. cap TTL so a transient error cannot poison a route forever;
4. decay old health observations after `TRACEWEAVE_ROUTER_HEALTH_TTL_SECONDS`.

Read `docs/PROVIDERS.md` for full configuration.

## 9. Evidence pipeline

Every fetched source can be scored independently on:

```text
relevance
importance
novelty
authority
```

Exact duplicates use SHA-256. Near duplicates use SimHash and are marked with `duplicate_of`; novelty is reduced rather than treating the copy as independent evidence.

For model-extracted claims, TraceWeave requires an exact evidence quote. A claim is persisted as grounded only if that quote is found literally in the stored snapshot text, with verified offsets.

Read `docs/EVIDENCE.md`.

## 10. Deep traversal

TraceWeave extracts ordinary links, citation/document-like links, RSS/Atom links and bounded sitemap candidates. Links enter a persistent best-first frontier.

Priority considers topic/angle overlap, anchor/path signals, document/citation hints, same-domain context, depth and obvious low-value URL penalties. Per-domain limits and a total frontier budget prevent crawl explosions.

`robots.txt` is respected by default:

```dotenv
TRACEWEAVE_RESPECT_ROBOTS=true
```

Read `docs/FRONTIER.md`.

## 11. Browser fallback

Default is normal HTTP collection. To opt into Crawl4AI for JS-heavy pages:

```bash
pip install -e '.[browser]'
crawl4ai-setup
```

```dotenv
TRACEWEAVE_BROWSER_FALLBACK=true
TRACEWEAVE_BROWSER_MIN_TEXT_CHARS=500
```

On an 8 GB VPS keep browser concurrency conservative. Browser fallback should be exceptional, not the default path for every page.

## 12. Persistent data

Default:

```text
.traceweave/
├── traceweave.db
├── sources/
│   └── SOURCE_ID/
│       ├── HASH.raw.gz
│       └── HASH.txt
└── exports/
```

Move it with:

```dotenv
TRACEWEAVE_DATA_DIR=/var/lib/traceweave
```

v0.3 migrations are additive and run when storage initializes. Back up `.traceweave/` before major upgrades anyway.

## 13. Sessions vs runs

A **run** is durable research state. A **session** is TUI workspace state.

A session remembers the active run, angle, mode, language, onboarding and local-shell toggle. Closing the TUI does not delete either one.

## 14. Configuration reference

See `.env.example`, `providers.example.toml`, and `docs/CONFIGURATION.md`.

Important operational variables include:

```text
TRACEWEAVE_FETCH_CONCURRENCY
TRACEWEAVE_ROUTER_MAX_ATTEMPTS
TRACEWEAVE_ROUTER_HEALTH_TTL_SECONDS
TRACEWEAVE_CLAIMS_MAX_SOURCES_PER_ROUND
TRACEWEAVE_FRONTIER_MIN_SCORE
TRACEWEAVE_FRONTIER_PER_DOMAIN_LIMIT
TRACEWEAVE_BROWSER_FALLBACK
TRACEWEAVE_SHELL_ENABLED
```

## 15. Tests

Development setup:

```bash
pip install -e '.[dev]'
python -m compileall -q src tests scripts
ruff check src tests
pytest
python scripts/smoke_test.py
python scripts/smoke_stage23.py
python -m build
```

The Stage 2/3 smoke test runs an offline fake search + fake model workflow through planning, search, snapshot, triage, grounded claim extraction, frontier traversal, re-planning and synthesis.

## 16. Troubleshooting

### No usable model routes

```bash
traceweave doctor
traceweave providers
```

Check that `providers.toml` exists and every `token_env` environment variable is actually set. TraceWeave can still collect using deterministic fallback behavior without a model, but model triage/claims/synthesis will be limited.

### Route stuck in cooldown

```bash
traceweave providers --task planning
traceweave router-log
```

Look at which scope failed. Do not rotate or delete all provider configuration because one token got a 429.

### Search returns nothing

Check SearXNG reachability. With `auto`, TraceWeave can fall back to DDGS, but public upstream engines may rate limit it.

### Interrupted research

```bash
traceweave runs
traceweave resume RUN_ID
```

Pending queries and abandoned frontier leases are durable.
