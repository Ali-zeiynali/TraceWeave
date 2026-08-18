# TraceWeave v0.1 Usage Guide

This guide covers the Stage-1 interface and operational behavior.

## 1. Starting the application

Full-screen terminal UI:

```bash
traceweave
```

or explicitly:

```bash
traceweave tui
```

Normal CLI:

```bash
traceweave --help
```

## 2. TUI layout

The UI contains three live panels:

- **PLAN / STATE** — current round objective, focus areas and generated queries.
- **SOURCES** — sources as they are discovered, with source ID, type, title and domain.
- **LIVE TRACE** — research events, fetch failures, round completion and exports.

The command line at the bottom accepts either a plain research topic or a slash command.

Textual also provides its built-in command palette with **Ctrl+P**.

## 3. TUI commands

```text
/research TOPIC
```

Starts a new run.

```text
/angle TEXT
```

Changes the current research lens. The angle is supplied to the planner and synthesis layer.

```text
/mode quick
/mode standard
/mode deep
```

Default round counts if `/rounds` is not set:

- quick: 1
- standard: 2
- deep: 3

```text
/rounds 4
```

Overrides the round count for newly started research. v0.1 allows 1–8 rounds.

```text
/runs
```

Shows recent run IDs and statuses.

```text
/resume
/resume RUN_ID
```

Resumes the latest run or a specific run.

```text
/export
/export RUN_ID
```

Creates a Markdown export under `.traceweave/exports/`.

```text
/clear
/help
/quit
```

Utility commands.

## 4. Keyboard shortcuts

- `Ctrl+L` — focus command input.
- `Ctrl+R` — resume latest run.
- `Ctrl+E` — export latest run.
- `Ctrl+K` — clear live log.
- `Ctrl+Q` — quit.
- `F1` — help.
- `Ctrl+P` — Textual command palette.

## 5. CLI research

```bash
traceweave research "renewable energy company X"
```

With explicit controls:

```bash
traceweave research "renewable energy company X" \
  --angle "ownership, projects, technology and historical changes" \
  --mode deep \
  --rounds 3 \
  --language all
```

## 6. What happens in each round

For round 1:

1. planner receives the ResearchSpec;
2. planner creates a small set of diverse queries;
3. each query is persisted as `pending`;
4. search executes;
5. every result is persisted immediately;
6. the highest-ranked results are fetched within bounded concurrency;
7. successful source snapshots are content-hashed and stored;
8. query becomes `completed`;
9. round becomes `completed`.

Before round 2, the planner receives a compact state containing completed queries and the most relevant source capsules. It creates a new plan rather than repeating the first plan.

If the process dies after the plan was saved but before all queries completed, a resume reuses the saved plan and only executes unfinished queries.

## 7. Source provenance

A result is not discarded merely because its page cannot be fetched.

For every search discovery TraceWeave records:

```text
run ID
source ID
original URL
canonical URL
title
domain
search query
search rank
search engine / backend
category (web/news)
published date, when supplied
raw search-result metadata
discovery time
```

A successful fetch additionally records:

```text
fetch time
final URL
HTTP status
content type
SHA-256 hash
compressed raw snapshot path
extracted-text path
page title
```

This distinction is important: **discovery provenance** and **page snapshot evidence** are separate records.

## 8. Files on disk

The data directory can be moved:

```dotenv
TRACEWEAVE_DATA_DIR=/var/lib/traceweave
```

Default:

```text
.traceweave/
```

For an Ubuntu service account you might use:

```bash
sudo mkdir -p /var/lib/traceweave
sudo chown "$USER":"$USER" /var/lib/traceweave
```

then set the environment variable.

## 9. Search backends

### auto

Recommended for Stage 1:

```dotenv
TRACEWEAVE_SEARCH_BACKEND=auto
```

Order:

```text
SearXNG → DDGS
```

### SearXNG

```dotenv
TRACEWEAVE_SEARCH_BACKEND=searxng
TRACEWEAVE_SEARXNG_URL=http://127.0.0.1:8080
```

The instance must allow `format=json`.

### DDGS

```dotenv
TRACEWEAVE_SEARCH_BACKEND=ddgs
```

This requires no search API key, but upstream engines can change, block or rate-limit automated requests. Treat it as a practical Stage-1 fallback rather than a guaranteed long-term search infrastructure.

## 10. LLM endpoint

Stage 1 supports OpenAI-compatible chat completions:

```dotenv
TRACEWEAVE_API_BASE=https://provider.example/v1
TRACEWEAVE_API_KEY=...
TRACEWEAVE_MODEL=...
```

The model is used for two narrow responsibilities:

- planning/re-planning;
- final research brief.

It does **not** execute search tools directly. This makes v0.1 usable with smaller routers that do not implement reliable tool calling.

### No model configured

This is valid.

TraceWeave uses deterministic query plans and still performs:

- iterative rounds;
- search;
- source preservation;
- snapshots;
- run history;
- resume;
- export.

The final brief becomes a source inventory instead of an LLM synthesis.

## 11. Resume behavior

Possible statuses:

```text
created
running
paused
failed
completed
```

A Ctrl+C interruption in CLI leaves durable database state. In the TUI, cancelling the active worker marks the run paused when cancellation reaches the engine.

Resume:

```bash
traceweave resume abc123def456
```

Research plans are stored per round, so resuming does not ask the model to reconstruct the previous plan from chat history.

## 12. Export

Markdown:

```bash
traceweave export RUN_ID
```

Contains:

- run metadata;
- research brief;
- source inventory;
- discovery query/rank/backend;
- snapshot status;
- event trail.

JSON:

```bash
traceweave export RUN_ID --format json
```

Mermaid research-flow graph:

```bash
traceweave export RUN_ID --format mermaid
```

The `.mmd` file represents `run → round → query → discovered source` and can be rendered later without requiring a graph database in Stage 1. JSON is useful for later migrations and richer visualizers.

## 13. Diagnostics

```bash
traceweave doctor
```

Then test the project itself:

```bash
python -m compileall -q src tests
pytest
python scripts/smoke_test.py
```

## 14. Common problems

### SearXNG gives HTTP 403/429 or non-JSON output

Verify that your instance enables JSON output and is intended for API use. Try:

```bash
curl 'http://127.0.0.1:8080/search?q=test&format=json'
```

or temporarily use:

```dotenv
TRACEWEAVE_SEARCH_BACKEND=ddgs
```

### DDGS fails intermittently

Its upstream search services can rate-limit or change behavior. Retry later or use your own SearXNG instance.

### Model provider rejects JSON planning

v0.1 parses a JSON object even if a provider wraps it in additional text. If the provider consistently returns invalid data, clear the three LLM environment variables and verify that deterministic mode works, then switch to a more compatible endpoint.

### A source is present but `Fetched = no`

This is expected when:

- the page blocks the request;
- DNS failed;
- it redirects to a private/reserved destination;
- it is not text/HTML in Stage 1;
- it exceeds the configured byte limit;
- it times out.

The search-discovery record remains preserved.

## 15. Operational recommendation for an 8 GB VPS

Stage 1 is intentionally a single-process research app plus SQLite. Use conservative fetch concurrency (`3` by default). Do not add a browser worker, graph database, Redis or a local LLM yet.

For overnight CLI research:

```bash
tmux new -s traceweave
source .venv/bin/activate
traceweave research "TOPIC" --mode deep --rounds 3
```

Detach with `Ctrl+B`, then `D`.
