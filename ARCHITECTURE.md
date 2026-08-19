# TraceWeave v0.3 Architecture

TraceWeave is deliberately split into a **reasoning plane** and a **deterministic data plane**. Models plan, re-plan, triage, extract grounded claims and synthesize. Python owns search, crawling, persistence, provenance, routing, retries, frontier scheduling and resume.

## 1. Core invariant

```text
ResearchSpec
    ↓
PLAN (bounded)
    ↓
SEARCH + STORE DISCOVERY
    ↓
FETCH + SNAPSHOT
    ↓
TRIAGE + GROUNDED CLAIMS
    ↓
BEST-FIRST FRONTIER
    ↓
ASSESS GAPS / LEADS
    ↓
RE-PLAN
    ↓
... bounded rounds ...
    ↓
SYNTHESIS FROM STORED EVIDENCE
```

A run must remain understandable and resumable without relying on model conversation history.

## 2. Runtime boundaries

```text
┌─────────────────────────────────────────────────────────────┐
│ TUI / CLI                                                   │
└───────────────────────────┬─────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ ResearchEngine                                               │
│ plan → search → analyze → frontier → re-plan → synthesize   │
└───────┬───────────────────┬───────────────────┬─────────────┘
        │                   │                   │
        ↓                   ↓                   ↓
 SearchBackend          ModelRouter        FrontierManager
        │                   │                   │
        ↓                   ↓                   ↓
 SearXNG/DDGS       provider/token/model    SafeFetcher
                            │               Crawl4AI optional
                            ↓
                     task-specific prompts
                     progressive skills
        └───────────────────┬───────────────────┘
                            ↓
                        Storage
              SQLite + files + durable events
```

`runtime.build_runtime()` is the composition root. Concrete adapters should be wired there rather than imported throughout unrelated modules.

## 3. Durable model

### Research state

- `runs`: immutable request parameters plus lifecycle/current round.
- `plans`: the exact plan saved for each round, including gaps and source classes.
- `queries`: resumable query work units with status.
- `events`: append-oriented research/runtime trail.

### Provenance

- `sources`: canonical resource identity.
- `run_sources`: every discovery edge from a query/frontier to a source. Multiple engines/categories/queries are preserved independently.
- `snapshots`: fetched content versions with SHA-256, SimHash, raw gzip body and extracted text.

A failed fetch never erases the original discovery.

### Evidence

- `source_analysis`: relevance, importance, novelty, authority, topics, leads, source family and duplicate relation.
- `claims`: atomic claim records.
- `evidence`: exact quote, source id, snapshot hash and verified character offsets.

A model-proposed quote must literally occur in the stored snapshot before TraceWeave persists it as grounded evidence.

### Deep traversal

- `frontier`: durable best-first URL queue with parent source, relation, anchor, depth, score, domain and status.
- `domain_state`: per-run/domain crawler metadata such as sitemap/robots work.

Frontier state is `pending → leased → completed|failed`. Abandoned leases are returned to pending on resume.

### Sessions

- `sessions`: TUI/workspace state such as active run, angle, mode, language, onboarding and local-shell toggle.

A session is not a research run. Several UI sessions may point at different durable runs.

### Router health

- `router_credentials`: token/credential health. No raw token is persisted.
- `router_deployments`: `provider + credential + model` health.
- `router_task_health`: deployment + task suitability health.
- `router_attempts`: auditable routing outcomes without secrets.

## 4. Provider-router failure scopes

The fundamental routing candidate is:

```text
provider + credential/token + model
```

TraceWeave intentionally has **no hard provider-wide poisoning**.

### Credential scope

`401`, `403`, `429` and quota/auth failures affect the configured credential id. Every model using that token may cool down, but other tokens from the same provider remain eligible.

### Deployment scope

Timeout, transient network/upstream failure, model/request mismatch or malformed endpoint behavior affects only `token + model`.

### Task scope

Refusal-style output or structured-JSON failure affects only `token + model + task` so a model can be unsuitable for `replanning` yet remain useful for `triage`.

Cooldown TTL prefers upstream reset hints such as `Retry-After`; otherwise bounded exponential backoff is used by failure class. Historical latency/failure observations decay after `TRACEWEAVE_ROUTER_HEALTH_TTL_SECONDS`, while an active absolute cooldown is still honored.

## 5. Why tool calling is not required

Models never own the crawler or shell. The minimal model contract is:

```text
json(system, user, task) -> dict
text(system, user, task) -> str
```

This keeps ordinary OpenAI-compatible endpoints useful even when their function/tool calling is absent or unreliable. The orchestrator executes search, fetch, persistence and traversal.

## 6. Planning and context discipline

The initial planner receives the `ResearchSpec`, not the whole future research tree. Every later round receives a compact state consisting of completed queries, high-value sources, grounded claims, gaps and leads.

Raw pages remain outside model context. `ContextBuilder` behavior is currently distributed between planner/analyzer/engine payload builders; later long-memory stages can extract that into a dedicated retrieval component without changing the evidence schema.

## 7. Search and collection

Search adapters normalize to:

```text
url
title
snippet
engine
category
published_at
raw metadata
```

Stage 3 collection ladder:

```text
SearXNG / DDGS discovery
        ↓
SafeFetcher (default)
        ↓ if JS-heavy and explicitly enabled
Crawl4AI BrowserFetcher
```

`SafeFetcher` validates public HTTP(S) targets, resolves and rejects private/reserved destinations, re-validates redirects, limits bytes/time, extracts links/text and does not inherit ambient proxy variables.

## 8. Best-first traversal

`max_depth` is only a ceiling. Each link is scored using topic/angle overlap, anchor/path signals, citation/document hints, domain context and low-value path penalties. Global run budget plus per-domain limits prevent a single site from consuming the investigation.

This avoids breadth explosions while still allowing a high-value obscure link several hops away to enter a later re-plan.

## 9. Prompt and skill layout

`src/traceweave/prompts/` contains task-specific contracts:

- `initial_plan.txt`
- `replan.txt`
- `triage.txt`
- `claims.txt`
- `synthesis.txt`

`src/traceweave/skills/` contains compact procedural knowledge. `SkillRegistry` progressively loads only skills relevant to the current task, so the base prompt does not carry every research procedure on every call.

Web/source text is always treated as **untrusted data**, never executable instructions.

## 10. TUI boundary

The Textual application only invokes normal runtime APIs and renders `ProgressEvent`s. No research algorithm should live exclusively in a widget. This keeps the same engine usable via TUI, CLI, future API service and background workers.

The v0.3 UI starts with onboarding + command input only. The workspace appears after `/research`, `/resume`, or a command that has meaningful data to display. The old footer was removed entirely.

## 11. Resource strategy for an 8 GB VPS

Default v0.3 stays deliberately small:

```text
TraceWeave Python process
SQLite
HTTP client
Textual TUI
SearXNG optional external service
```

Crawl4AI and LiteLLM are optional extras. Neo4j, Qdrant, Elasticsearch, Kafka, Temporal and local large models are not default dependencies.

## 12. Stable extension points

Later stages should extend, not replace, these boundaries:

- `SearchBackend` for OpenAlex/Crossref/arXiv/GitHub/archives.
- `ModelRouter` drivers and capability-aware scheduling.
- `FrontierManager` scoring/reranking.
- evidence/source-family analysis.
- entity/relationship graph tables layered over existing source/claim provenance.
- workers/queues outside the engine when one process is no longer sufficient.

The invariant to preserve is: **durable evidence and state live outside model context; model outputs are proposals until deterministic validation/persistence accepts them.**
