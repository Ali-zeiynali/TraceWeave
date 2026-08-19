# TraceWeave v0.5

TraceWeave is an open-source, evidence-first research engine for iterative public-web research. It is designed around a simple loop:

`PLAN → SEARCH → COLLECT → TRIAGE → FOLLOW LEADS → RE-PLAN → VERIFY → SYNTHESIZE`

It is deliberately **not** a single giant agent prompt. Crawling, provenance, persistence, archive lookup, deduplication, routing, graph state, and resume are normal software components; language models are used where judgment is useful.

## What v0.5 adds

- Stage 4 specialist discovery: Wayback CDX, Common Crawl, OpenAlex, Crossref, arXiv, public GitHub search, PDF parsing, citation snowballing.
- Stage 5 foundation: claim-grounded entities, relationships, timeline events, and a research-edge graph in SQLite.
- Credential-scoped model catalogs: provider → token → model. Different tokens on the same router may expose different models.
- Dynamic routing health at credential, deployment (`token+model`), and task (`token+model+task`) levels.
- Dynamic cooldown from `Retry-After` / rate-limit headers plus exponential fallback TTLs.
- Built-in provider presets activated by `.env`; up to three tokens/provider without writing TOML.
- Minimal OpenCode-style TUI landing screen: centered input, folder, selected planning route, rotating tip. Workspace appears only after research starts or is resumed.
- Durable sessions, pause/resume, full source provenance, archives/citations/graph exports.

## Safety / scope

TraceWeave v0.5 is designed for public, lawful research. It respects `robots.txt` for normal live crawling, blocks private/link-local targets in the fetcher, treats page content as untrusted data, and does not grant fetched pages or models autonomous shell access. The optional local shell is user-triggered and disabled by default.

This project does not include private-person tracking, inferred private routines/precise locations, credential harvesting, access-control bypass, or unauthorized active network scanning.

## Quick start

Requirements: Python 3.11+.

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[stage4]"
Copy-Item .env.example .env
traceweave doctor
traceweave
```

### Ubuntu VPS

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[stage4]'
cp .env.example .env
traceweave doctor
traceweave
```

For optional provider adapters via LiteLLM:

```bash
pip install -e '.[stage4,providers]'
```

For optional JS/browser fallback:

```bash
pip install -e '.[full]'
crawl4ai-setup
```

Browser fallback is off by default and should remain limited on an 8 GB VPS.

## Provider mesh: zero-config path

Put any keys you have in `.env`:

```dotenv
GROQ_API_KEY=...
GROQ_API_KEY_2=...
GROQ_API_KEY_3=...

GEMINI_API_KEY=...
OPENROUTER_API_KEY=...
MISTRAL_API_KEY=...
ZENMUX_API_KEY=...
SEEKROUTER_API_KEY=...
AGENTROUTER_API_KEY=...
```

Each provider accepts `KEY`, `KEY_2`, and `KEY_3` (`KEY_1` is also accepted instead of the unnumbered first key). Raw tokens are never persisted in router-health or catalog files.

Built-in presets currently cover:

| Provider | Strategy |
|---|---|
| Groq | curated strong/fast GPT-OSS and Qwen routes |
| Gemini | curated current Flash / Flash-Lite routes suitable for Free Tier where available |
| Mistral | `mistral-small-latest` bootstrap + per-token `/models` discovery |
| OpenRouter | `openrouter/free` + per-token dynamic zero-price model catalog |
| ZenMux | curated `*-free` GLM routes + dynamic zero-price filtering; requires an API-enabled ZenMux account |
| AgentRouter | curated strong bootstrap models + per-token `/models` discovery |
| SeekRouter | per-token `/models` discovery; base URL is overrideable |

Run:

```bash
traceweave providers --sync --task planning
traceweave providers --task triage
traceweave router-log
```

`providers.toml` is optional and is only needed for overrides/custom endpoints. See `docs/PROVIDERS.md`.

## TUI

At startup TraceWeave shows only a centered input, current folder, current planning route/model, and one randomized tip. It does not render empty research panels before a run exists.

Type a topic directly or use commands:

```text
/research semiconductor supply chain in Europe
/angle ownership, suppliers and historical changes
/mode deep
/depth 3
/budget 30
/providers sync
/pause
/resume
/archives
/citations
/entities
/timeline
/export mermaid
```

Use `F1` for in-app help. Command suggestions use Textual's input suggester; Right Arrow accepts a suggestion. Up/Down traverses local command history. Submitted commands are cleared automatically.

## Stage 4 source flow

```text
Generic search
    ├── SearXNG / DDGS
    ├── OpenAlex / Crossref / arXiv
    ├── GitHub public repositories/issues
    └── fetched PDFs
             ↓
      evidence triage
             ↓
  DOI / arXiv / URL citations
             ↓
      best-first frontier
             ↓
  Wayback / Common Crawl history
             ↓
          re-plan
```

A historical capture is stored as time-scoped evidence and does not overwrite the current page. Successful archive checks are stateful per run/source/engine so resume does not repeatedly hit the same archive API.

## Evidence and graph invariants

- A search result is saved before page fetching, so a later fetch failure does not erase provenance.
- Every discovery path keeps query, engine, category, rank, and timestamp.
- Claim extraction only accepts an `evidence_quote` that occurs literally in the stored snapshot.
- Exact/near duplicate detection prevents repeated copies from looking like independent evidence.
- Graph relationships must point to an existing grounded claim ID. Invalid model-generated graph relationships are discarded.
- Timeline events are produced from grounded claim dates, not invented chronology.

## Data directory

Default `.traceweave/` contains SQLite state, compressed source snapshots, archive captures, exports, catalog metadata, and durable sessions. It is intentionally ignored by Git.

Back up `.traceweave/traceweave.db*` and `.env` before moving machines.

## Tests

```bash
pip install -e '.[dev,stage4]'
python -m compileall -q src tests scripts
pytest
python scripts/smoke_test.py
python scripts/smoke_stage23.py
python scripts/smoke_stage45.py
python -m build
```

## Documentation

- `USAGE.md` — operator guide and TUI commands
- `ARCHITECTURE.md` — component boundaries, state, routing and long-horizon design
- `docs/PROVIDERS.md` — provider/token/model routing
- `docs/STAGE4.md` — archives, academic, GitHub, PDF and citation flow
- `docs/GRAPH.md` — Stage 5 graph foundation
- `docs/CONFIGURATION.md` — environment reference
- `docs/EVIDENCE.md` / `docs/FRONTIER.md` — evidence and traversal invariants
- `ROADMAP.md` — v0.5 → v1.0

## License

MIT. See `LICENSE`.
