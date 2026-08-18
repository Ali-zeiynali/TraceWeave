# TraceWeave v0.1 Architecture

This document defines the boundaries that should remain stable while TraceWeave grows from Stage 1 to the later roadmap.

## 1. Core rule

The language model is **not** the runtime, database, browser, queue, or memory system.

It is a replaceable reasoning component used at explicit boundaries.

```text
LLM
 ├─ may propose a plan
 └─ may synthesize bounded evidence

TraceWeave
 ├─ owns research state
 ├─ executes search
 ├─ fetches sources
 ├─ stores provenance
 ├─ records events
 ├─ resumes work
 └─ exports results
```

This rule is the main reason Stage 1 can later support unstable free providers without rewriting the research loop.

## 2. Module map

```text
src/traceweave/
├── cli.py                  Typer command-line interface
├── tui/app.py              Textual full-screen UI
├── config.py               environment/configuration model
├── models.py               typed research domain objects
├── runtime.py              composition root / dependency wiring
├── engine.py               iterative orchestration
├── planner.py              plan + re-plan policy
├── fetcher.py              bounded public HTTP text/HTML fetcher
├── storage.py              durable SQLite state + provenance
├── exporter.py             Markdown/JSON/Mermaid exports
├── utils.py                canonicalization / parsing helpers
│
├── providers/
│   ├── base.py             LLM protocol
│   ├── factory.py          provider construction
│   └── openai_compat.py    Stage-1 generic chat-completions adapter
│
├── search/
│   ├── base.py             normalized search protocol
│   ├── factory.py          search-backend selection
│   ├── searxng.py          SearXNG adapter
│   └── ddgs_backend.py     DDGS adapter
│
└── prompts/
    ├── initial_plan.txt
    ├── replan.txt
    └── synthesis.txt
```

## 3. Composition root

`runtime.build_runtime()` is the only place that should normally wire concrete implementations together.

The engine receives abstract responsibilities:

```text
Storage
SearchBackend
Planner
LLMProvider | None
ProgressCallback | None
```

Later provider meshes, queues, graph stores or alternative search adapters should be introduced through composition instead of imported directly throughout the application.

## 4. Research state machine

Conceptually:

```text
CREATED
   ↓
RUNNING
   ↓
ROUND N
   ├─ get/create plan
   ├─ persist plan
   ├─ resume pending queries
   ├─ search
   ├─ persist each discovery immediately
   ├─ fetch selected sources
   ├─ persist snapshots
   └─ commit round number
   ↓
RE-PLAN FROM COMPACT STATE
   ↓
NEXT ROUND
   ↓
SYNTHESIS
   ↓
COMPLETED
```

Interruptions can produce `paused` or `failed`. A later `resume` loads durable state rather than reconstructing it from conversation history.

## 5. Persistence model

### runs

One research request and its durable lifecycle.

### plans

One plan per round. The exact plan is preserved so a resume never needs to regenerate it.

### queries

Each query has its own status. This is the basic unit of resumable search work in v0.1.

### sources

Canonical web resource identity. Tracking parameters are stripped for identity, while the original discovered URL is retained.

### run_sources

The **discovery edge** between a run and a source. This is deliberately separate from `sources` because the same URL may be discovered:

- by multiple queries;
- at different ranks;
- from different search engines;
- as web and/or news material.

Every discovery edge retains its own metadata and raw search result. Distinct engines/categories are preserved even when they expose the same canonical URL for the same query.

### snapshots

Fetched content versions identified by hash. Search discovery can exist without a snapshot.

### events

Append-style operational/research trail used by the TUI today and richer visualization/observability later.

## 6. Why discovery and snapshot are separate

A common crawler design accidentally equates:

```text
fetch failed == source never existed
```

TraceWeave does not.

```text
Search result
   ↓ always persisted
Discovery record
   ↓ fetch attempted
Snapshot (optional)
```

This preserves obscure sources even when a site disappears, blocks automated clients, times out, or becomes an archive target in a future stage.

## 7. Planning boundary

Stage 1 uses two planning functions:

```text
initial(spec)
replan(spec, completed_queries, source_capsules)
```

The second call receives a **compact** state. It does not receive all raw pages or the entire event history.

Future versions should keep this property when they add:

- claims;
- gaps;
- graph neighborhoods;
- timelines;
- branch notebooks;
- coverage scores.

## 8. Search adapter contract

A backend returns normalized `SearchResult` objects:

```text
url
title
snippet
engine
category
published_at
raw metadata
```

New adapters should normalize at the boundary rather than force the engine to understand each search provider's schema.

Likely future adapters:

```text
OpenAlex
Crossref
GitHub
Wayback
Common Crawl
RSS
site-specific public APIs
```

## 9. Provider boundary

Stage 1 does not ask the model to invoke tools.

The minimal provider interface is:

```text
json(system, user) -> object
text(system, user) -> text
```

This intentionally supports endpoints that provide ordinary chat completions but weak or nonexistent function/tool calling.

In v0.6 the provider factory can become a capability-aware router while keeping `Planner` and `ResearchEngine` mostly unchanged.

## 10. Fetch boundary

`SafeFetcher` is for ordinary public text/HTML collection only.

Its responsibilities are intentionally narrow:

- validate public HTTP/HTTPS targets;
- validate redirects;
- limit bytes;
- limit time;
- extract readable text;
- produce a content hash.

It should not grow into a browser automation framework.

Later:

```text
ordinary HTTP → SafeFetcher
JS page       → Crawl4AI adapter
interaction   → Playwright worker
PDF           → document pipeline
```

## 11. TUI boundary

The TUI observes `ProgressEvent` objects and calls normal engine/export APIs. Research logic should never be implemented only inside widgets.

This ensures the same engine remains usable through:

- TUI;
- CLI;
- SSH/tmux;
- future HTTP API;
- scheduled jobs.

## 12. Mermaid export

Stage 1 can already export:

```text
run → round → query → source
```

as Mermaid.

This is intentionally generated from ordinary relational state. It gives us a visual research trail now without committing to Neo4j or another graph database before graph requirements are mature.

## 13. Stage-2 extension points

The next milestone should add evidence structures without replacing Stage-1 primitives.

Expected additions:

```text
documents
chunks
claims
evidence_spans
source_scores
source_families
```

`source_id` and snapshot hashes should remain provenance anchors.

## 14. Resource strategy for the 8 GB target VPS

Stage 1 deliberately avoids:

- Redis;
- Neo4j;
- Qdrant;
- Elasticsearch;
- Playwright browsers;
- local LLMs;
- Temporal;
- Kafka.

The target runtime is therefore approximately:

```text
TraceWeave process
SQLite
network connections
optional external/self-hosted SearXNG
```

Later services should be introduced only when their capability is actually needed.

## 15. Non-negotiable invariants for future stages

1. A discovered source is recorded before optional expensive processing.
2. Raw evidence is never replaced by an LLM summary.
3. A plan is persisted before its searches execute.
4. Model/provider identity is not embedded in core research logic.
5. External content cannot issue trusted instructions merely by appearing on a page.
6. Resume operates from durable structured state, not narrative chat memory.
7. Every output claim added in later stages must be traceable back to evidence/source state.
