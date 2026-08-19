# TraceWeave

**TraceWeave is an open-source, evidence-first, iterative research engine for the public web.**

It is designed around a simple rule: a long investigation should not be one giant prompt. TraceWeave repeatedly plans a bounded round, searches and collects evidence, assesses what changed, updates durable state, and then re-plans.

```text
PLAN → SEARCH → STORE → ASSESS → RE-PLAN → TARGETED SEARCH → … → SYNTHESIS
```

Version **0.3.0** combines Stage 2 (Evidence & Triage) and Stage 3 (Best-First Deep Traversal) on top of the v0.1 research core. The provider mesh was intentionally accelerated into v0.3 because provider instability and multi-token routing are foundational for long-running free/credit-based deployments.

## What v0.3 does

- Full-screen Textual TUI with persistent sessions and onboarding.
- Iterative plan/search/re-plan loop; plans are persisted per round.
- Complete search provenance before page fetch: original URL, canonical URL, query, rank, engine, category/news type, publication date when available, raw search metadata and discovery time.
- Bounded HTTP snapshot collection with SSRF protections and raw/text storage.
- Source triage: relevance, importance, novelty and authority.
- Exact/near duplicate detection using content hashes + SimHash.
- Grounded atomic claims: evidence quotes are persisted only when the quote literally occurs in the stored source text.
- Source-family/duplicate metadata as a foundation for later source-independence analysis.
- Best-first research frontier with semantic/structural scoring, depth ceiling, page budget and per-domain limits.
- Recursive page-link discovery plus RSS/Atom and bounded sitemap discovery.
- `robots.txt` respected by default.
- Optional Crawl4AI fallback for JavaScript-heavy pages.
- Persistent resume: run state, queries, plans, frontier leases, snapshots, claims, router health and sessions survive restart.
- Multi-provider / multi-token / multi-model router.
- Credential/token-level cooldown for authentication/quota failures; token+model deployment health for model/network failures; token+model+task penalties for refusal/JSON-format failures.
- Dynamic cooldown TTL using upstream `Retry-After` / rate-limit reset hints when available, otherwise bounded exponential backoff.
- Stale health observations decay after a configurable health-observation TTL.
- Direct OpenAI-compatible driver plus optional LiteLLM driver for broad native provider support.
- Progressive bundled skills: only task-relevant compact instructions enter model context.
- Markdown, JSON, Mermaid research graph and evidence-matrix exports.
- Local shell command support in TUI, disabled by default and persisted per session when enabled.

## What it intentionally does not do yet

v0.3 is not a massive distributed crawler, not a vulnerability scanner, and not a private-person tracking system. It focuses on public-web research. Neo4j, Qdrant, Elasticsearch, Kafka, Kubernetes and large local models are deliberately absent from the default stack so the tool stays usable on an 8 GB VPS.

The Stage 4+ roadmap adds archives, academic adapters, richer GitHub/public-code analysis, richer entity resolution and knowledge graphs without replacing the v0.3 data model.

## Quick start

### Existing TraceWeave v0.1 repository

Use the Stage 2+3 PowerShell patch delivered with this release:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\TraceWeave-patch-v0.1-to-v0.3.ps1
```

The patch backs up files it replaces, preserves `.traceweave`, `.git`, `.env` and an existing `providers.toml`, migrates SQLite in place on first run, installs the updated package, runs compile/tests/smoke tests and executes `traceweave doctor`.

### Manual installation / Ubuntu VPS

```bash
sudo apt update
sudo apt install -y python3 python3-venv git

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e .
cp -n .env.example .env
cp -n providers.example.toml providers.toml
traceweave doctor
traceweave
```

For broad native LLM provider support through LiteLLM:

```bash
pip install -e '.[providers]'
```

For the optional Crawl4AI browser fallback:

```bash
pip install -e '.[browser]'
crawl4ai-setup
```

Then set:

```dotenv
TRACEWEAVE_BROWSER_FALLBACK=true
```

The browser fallback is intentionally off by default because browser processes are substantially heavier than the normal HTTP path.

## First use

Start the TUI:

```bash
traceweave
```

The initial screen is deliberately small. Research panels appear only after a run is started or resumed.

Examples:

```text
/angle supply chain and technical infrastructure
/mode deep
/depth 3
/budget 40
/research Example Company
```

Or just type a research question directly.

CLI mode:

```bash
traceweave research "Example Company" \
  --mode deep \
  --angle "supply chain and infrastructure" \
  --depth 3 \
  --frontier-budget 40
```

## Provider routing

TraceWeave never requires a model to execute tools. Models receive bounded data and return text/JSON; the orchestrator executes search, fetch, storage and traversal itself. This keeps small or unstable OpenAI-compatible routers useful even when they have poor tool-call support.

A routing candidate is not just a provider. It is:

```text
provider + credential/token + model
```

For example, a provider with 3 tokens and 2 models can expose six independently routed deployments. Models may restrict which credentials they can use.

When Token A receives 429, TraceWeave cools Token A using `Retry-After` when supplied. Token B remains eligible. A refusal from Model X for task `replanning` penalizes only `Token + Model X + replanning`; it does not automatically poison the provider or the same model for unrelated tasks.

See [`docs/PROVIDERS.md`](docs/PROVIDERS.md) and [`providers.example.toml`](providers.example.toml).

## Source provenance and evidence

Search results are persisted *before* TraceWeave tries to fetch the page. A fetch failure therefore does not erase the lead.

A single canonical source may have many discovery paths:

```text
Query A ─┐
Query B ─┼─> Source S17
News    ─┤
Web     ─┘
```

Each path remains separately stored. Fetched snapshots are content-addressed and the raw bytes are gzip-compressed alongside extracted text.

Stage 2 adds source analysis and grounded claims. A model-proposed claim is not stored as grounded evidence unless its evidence quote can be located exactly in the saved text snapshot.

See [`docs/EVIDENCE.md`](docs/EVIDENCE.md).

## Best-first deep traversal

`depth=5` is a ceiling, not an instruction to visit every fifth-level link. Every discovered URL receives a score from topic/angle overlap, anchor text, citation/document signals, same-domain context and obvious low-value path penalties. The highest-value frontier items are visited first until the run's budget is exhausted.

This prevents combinatorial link explosions while still allowing obscure breadcrumb paths to change the direction of later planning rounds.

See [`docs/FRONTIER.md`](docs/FRONTIER.md).

## Persistent sessions

TUI sessions remember:

- active run
- mode
- angle
- language
- local-shell enabled/disabled state
- onboarding state

Commands:

```text
/session list
/session new investigation-a
/session switch SESSION_ID
/session rename new-name
```

Sessions are separate from research runs. A session is UI/workspace state; a run is durable research state.

During a long TUI run, `/pause` cancels the active research worker. The engine persists paused state, pending queries/frontier work remain durable, and `/resume` continues the same run. The session records the run id as soon as research begins rather than waiting for completion.

## TUI shell

Shell execution is **off by default**.

```text
/shell status
/shell enable
!git status
!python --version
/shell disable
```

Commands run locally with the operating-system permissions of the TraceWeave process. There is a timeout and output cap, but this is not a security sandbox. Do not enable it for untrusted users or expose a shell-enabled TUI through a shared service.

## Directory layout

```text
src/traceweave/
├── analysis.py             # triage + grounded claim extraction
├── engine.py               # iterative orchestration
├── exporter.py
├── fetcher.py              # SSRF-safe HTTP + optional browser fallback
├── frontier.py             # best-first recursive discovery
├── planner.py
├── storage.py              # durable SQLite schema + migrations
├── providers/
│   ├── config.py
│   ├── drivers.py
│   └── router.py
├── search/
├── prompts/                # role-specific system prompts
├── skills/                 # progressively loaded task skills
└── tui/
```

## Data layout

Default:

```text
.traceweave/
├── traceweave.db
├── sources/
│   └── 00000017/
│       ├── <sha256>.raw.gz
│       └── <sha256>.txt
├── exports/
├── logs/
└── sessions/
```

The SQLite database uses WAL mode. The raw API token value is never stored in router health tables; only configured credential ids are stored.

## Tests

```bash
pytest -q
python scripts/smoke_test.py
python scripts/smoke_stage23.py
python -m compileall -q src tests scripts
```

The v0.3 test suite covers Stage-1 provenance compatibility, v0.1 schema migration, session persistence, grounded quote rejection, frontier priority/depth behavior, token-scoped 429 cooldown and task-scoped refusal failover.

## Security and scope

TraceWeave's default research/fetch stack is for public-web material. The HTTP fetcher blocks private/reserved network destinations, re-validates redirects, caps document sizes and respects `robots.txt` by default. Web content is treated as untrusted data in all model prompts.

The project deliberately does not ship automatic credential harvesting, access-control bypass, private-person location inference or unrestricted remote scanning workflows. See [`SECURITY.md`](SECURITY.md).

## License

MIT. See [`LICENSE`](LICENSE).
