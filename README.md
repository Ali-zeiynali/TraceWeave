# TraceWeave

> Iterative public-web research with complete source provenance.

TraceWeave is an open-source research engine designed to grow from a small, usable terminal application into a long-horizon research system. Version **0.1** deliberately starts with a narrow, reliable core instead of pretending to be a complete autonomous OSINT platform.

The fundamental loop is:

```text
PLAN
  ↓
SEARCH + COLLECT
  ↓
STORE SOURCES + SNAPSHOTS
  ↓
ASSESS CURRENT STATE
  ↓
RE-PLAN
  ↓
TARGETED SEARCH
  ↓
...
  ↓
SYNTHESIZE / EXPORT
```

A plan is therefore **not** a giant one-shot plan created before research starts. Each round sees what the previous round discovered and decides what should be searched next.

## What v0.1 already does

- Full-screen terminal UI built with Textual.
- Normal CLI for automation and SSH use.
- Quick / Standard / Deep modes.
- Iterative `plan → search → re-plan → search` loop.
- Optional OpenAI-compatible LLM planner/synthesizer.
- Deterministic planner when no LLM is configured.
- Search abstraction with:
  - SearXNG backend.
  - DDGS fallback.
  - `auto` mode: prefer SearXNG, fall back to DDGS.
- Every discovered result is stored immediately, even if page fetching fails.
- Search provenance per source:
  - original URL;
  - canonical URL;
  - title;
  - domain;
  - search query that found it;
  - rank;
  - search engine/provider;
  - web/news category;
  - publication date when available;
  - raw result metadata.
- Safe text/HTML fetcher with:
  - redirect-by-redirect validation;
  - private/reserved-IP blocking;
  - response-size limit;
  - timeout;
  - bounded concurrency.
- Successful fetches are stored as:
  - compressed raw HTML/text;
  - extracted readable text;
  - SHA-256 content hash;
  - response metadata.
- SQLite WAL database.
- Durable research runs with resume after interruption/failure.
- Markdown and JSON export.
- Event/research trail for later visualization.
- Unit tests, offline smoke test, GitHub Actions CI, MIT license and contribution/security files.

## What v0.1 intentionally does **not** do

The following belong to later stages rather than being half-implemented now:

- deep recursive web crawling/frontier scheduling;
- Wayback/Common Crawl integration;
- PDF/document pipeline;
- entity/relationship knowledge graph;
- claim/evidence verification graph;
- provider capability routing and failover mesh;
- GitHub/OpenAlex/RDAP/DNS/CT/ASN specialist adapters;
- image/media intelligence;
- long-horizon distributed workers;
- active network scanning.

See [ROADMAP.md](ROADMAP.md) and [ARCHITECTURE.md](ARCHITECTURE.md).

## Architecture

```text
                    ┌──────────────────────┐
                    │  CLI / Textual TUI   │
                    └──────────┬───────────┘
                               │
                         ResearchSpec
                               │
                    ┌──────────▼───────────┐
                    │   ResearchEngine     │
                    └──────┬───────┬──────┘
                           │       │
                     ┌─────▼──┐ ┌──▼──────────┐
                     │Planner │ │SearchBackend│
                     └─────┬──┘ └──────┬──────┘
                           │           │
                 optional LLM      SearXNG / DDGS
                           │           │
                           └─────┬─────┘
                                 ▼
                           SafeFetcher
                                 │
                    ┌────────────▼─────────────┐
                    │ SQLite + source blobs   │
                    │ runs/plans/queries      │
                    │ sources/snapshots/events│
                    └──────────────────────────┘
```

The LLM never owns the durable state. State lives in ordinary storage and can be inspected or resumed without reconstructing a chat conversation.

## Requirements

- Python **3.11+**.
- Windows, Linux or macOS.
- Internet access for real research.
- Optional: an OpenAI-compatible API endpoint.
- Optional: your own SearXNG instance.

## Fast setup — Windows PowerShell

The repository includes `bootstrap-stage1.ps1`. If you only downloaded that file, place it in an otherwise empty directory and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\bootstrap-stage1.ps1
```

The script:

1. writes the complete v0.1 repository into the current directory;
2. creates `.env` from `.env.example`;
3. creates `.venv` when Python is available;
4. installs the package and development dependencies;
5. compiles the source;
6. runs the test suite;
7. runs the offline smoke test.

Use `-SkipInstall` if you only want to create the files:

```powershell
.\bootstrap-stage1.ps1 -SkipInstall
```

Use `-Force` only if you intentionally want to write into a non-empty directory.

## Manual installation

### Windows

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"
Copy-Item .env.example .env
traceweave doctor
traceweave
```

### Ubuntu / Debian VPS

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[dev]'
cp .env.example .env
traceweave doctor
traceweave
```

A full-screen Textual TUI works over a normal SSH terminal. For a long unattended run, use the CLI inside `tmux` or `screen`:

```bash
tmux new -s traceweave
traceweave research "your topic" --mode deep --rounds 3
```

## Configure a model

TraceWeave v0.1 deliberately uses a simple **OpenAI-compatible adapter** and does not require provider-native tool calling. Many providers and small routers expose this interface.

Edit `.env`:

```dotenv
TRACEWEAVE_API_BASE=https://YOUR-PROVIDER.example/v1
TRACEWEAVE_API_KEY=your-key
TRACEWEAVE_MODEL=your-model-id
```

The endpoint must support:

```text
POST {TRACEWEAVE_API_BASE}/chat/completions
```

If these values are blank, TraceWeave remains usable: it runs deterministic plans and performs collection, provenance storage, resume and export; it simply does not generate an LLM research brief.

### Why v0.1 does not rely on model tool-calling

Small/free providers frequently differ in tool-call formats or do not implement tools at all. Search and fetching are therefore executed by TraceWeave itself. The model receives a bounded research state and returns only a plan or synthesis. Later versions can add capability-aware routing without rewriting the research engine.

## Search configuration

Default:

```dotenv
TRACEWEAVE_SEARCH_BACKEND=auto
TRACEWEAVE_SEARXNG_URL=http://127.0.0.1:8080
```

`auto` first tries SearXNG. If it is unavailable or returns no results, it tries DDGS.

For a stable VPS deployment, running your own SearXNG is preferable to depending on public instances. SearXNG exposes a JSON search API at `/search`; enable JSON output on your instance and point `TRACEWEAVE_SEARXNG_URL` to it.

Force a backend:

```dotenv
TRACEWEAVE_SEARCH_BACKEND=searxng
```

or:

```dotenv
TRACEWEAVE_SEARCH_BACKEND=ddgs
```

DDGS is convenient for Stage 1 but may occasionally be rate-limited by its upstream search services.

## First research

TUI:

```bash
traceweave
```

Then type a topic directly, or:

```text
/angle corporate history and technical infrastructure
/mode standard
/rounds 2
/research Example Company
```

CLI:

```bash
traceweave research "Example Company" \
  --angle "history and technical infrastructure" \
  --mode standard \
  --rounds 2
```

List runs:

```bash
traceweave runs
```

Resume:

```bash
traceweave resume RUN_ID
```

Export:

```bash
traceweave export RUN_ID
traceweave export RUN_ID --format json
traceweave export RUN_ID --format mermaid
```

See [USAGE.md](USAGE.md) for all interactive commands, shortcuts, storage details and troubleshooting.

## Data layout

By default all runtime data is under `.traceweave/`:

```text
.traceweave/
├── traceweave.db
├── sources/
│   └── ab/
│       ├── <sha256>.html.gz
│       └── <sha256>.txt
└── exports/
    ├── <run-id>.md
    └── <run-id>.json
```

The database stores the relationship between a research run, a query, a source, and a stored snapshot. A source can be discovered by more than one query without duplicating its content blob.

## Security model in v0.1

TraceWeave treats web pages as **untrusted data**, not instructions. The v0.1 fetcher also blocks obvious private/reserved network destinations, validates every redirect target, limits downloaded bytes and supports only public HTTP/HTTPS text/HTML collection.

It is intended for public-web research. Do not use it to bypass access controls, authentication, paywalls or restrictions, and do not point it at systems you are not authorized to test.

See [SECURITY.md](SECURITY.md).

## Development

```bash
pip install -e '.[dev]'
python -m compileall -q src tests
ruff check src tests
pytest
python scripts/smoke_test.py
```

Build package artifacts:

```bash
python -m build
```

## Project status

`0.1.0` is an alpha foundation. Its API and database schema can still change before 1.0. The important guarantee of this stage is architectural: the durable research state, source provenance and orchestration are outside the LLM context from day one.

## License

MIT. See [LICENSE](LICENSE).
