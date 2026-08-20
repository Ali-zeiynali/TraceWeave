# TraceWeave v0.5 Architecture

## Design goal

TraceWeave is a long-horizon research runtime, not a chat transcript with tools. Durable state lives outside model context. The model sees small task-specific capsules assembled from persisted evidence.

```text
ResearchSpec / Session
        ↓
Planner ────────────────┐
        ↓               │
Generic Search          │
        ├─ SearXNG      │
        └─ DDGS         │
        ↓               │
Specialist Discovery    │
  ├─ OpenAlex           │
  ├─ Crossref           │
  ├─ arXiv              │
  └─ GitHub             │
  ├─ GLEIF/ROR/ORCID    │
  ├─ RDAP/DNS/RIPEstat  │
  └─ Bluesky/Telegram   │
        ↓               │
Fetch / Parse           │
  ├─ HTML/text          │
  ├─ PDF                │
  └─ optional Crawl4AI  │
        ↓               │
Evidence Analyzer       │
        ↓               │
Claims + Citation Leads │
        ↓               │
Archives                │
  ├─ Wayback            │
  └─ Common Crawl       │
        ↓               │
Best-first Frontier     │
        ↓               │
Graph Curator           │
        ↓               │
Gap-driven Re-planner ──┘
        ↓
Synthesizer / Exporter
```

The same run also has a durable work plane:

```text
ResearchSpec → deadline/budgets → leased research_tasks → checkpoint/result
                                    ↓
source → snapshot → media_lead → content-addressed artifact → region observation
```

## 1. Durable state boundaries

SQLite is the v0.5 durable state store. It holds:

- runs and per-round plans
- queries and their completion/error state
- canonical sources and every discovery path
- compressed snapshots and content hashes
- source analysis and grounded claims/evidence
- recursive frontier leases
- persistent TUI sessions
- provider credential/deployment/task health
- provider routing attempts
- archive captures and per-source Stage-4 completion state
- citations
- entities, relationships and timeline events
- research edges and event log
- leased research tasks/dependencies, deadline and model/vision budgets
- content-addressed artifacts, media leads and importance/rarity-scored observations

Large raw/text payloads are stored as compressed files under `.traceweave/` and referenced from SQLite.

## 2. Plan → collect → re-plan

A plan is intentionally one round. Re-planning receives bounded source capsules, grounded-claim capsules,
compact research-state counts, and high-value public observation capsules. The observation capsule carries the
actual OCR/visible text or metadata excerpt plus source/artifact IDs, locator, timestamp, confidence, importance,
and rarity. Raw observations remain local; known-irrelevant metadata and non-public observations are not sent.

This keeps low-context models usable and makes resume deterministic.

## 3. Provider mesh

The route identity is:

`provider + credential + model + task`

Health has three independent scopes:

1. credential (`provider:token`) — auth, quota, rate limit;
2. deployment (`provider:token:model`) — timeout, upstream/model-specific problems;
3. task (`provider:token:model:task`) — refusal or structured-output failure.

### Credential-scoped model catalog

Dynamic providers are queried per token. Cache shape:

```json
{
  "providers": {
    "router-x": {
      "token-1": [{"id": "model-a"}],
      "token-2": [{"id": "model-b"}]
    }
  }
}
```

A model discovered for token-1 is never automatically bound to token-2.

Catalog TTL and catalog-failure retry are separate from request health. A shared async lock prevents concurrent model calls from stampeding `/models` on refresh.

## 4. Stage 4 source adapters

Specialist adapters return normalized `SpecialistResult` objects and then enter the same source/provenance/evidence system as generic web results.

### Academic
OpenAlex, Crossref, and arXiv are searched independently. Failures in one source do not abort the others.

### GitHub
Only public repository and issue search is used in v0.5. Authentication is optional and only increases normal public API capacity.

### Archives
Wayback CDX finds time-separated captures. Common Crawl locates indexed WARC records and range-fetches selected captures. A capture has its own timestamp, engine, digest and source relationship.

A successful archive check is marked in `source_stage_state`, so the same run does not repeat completed archive API work every round. Temporary errors remain retryable.

### PDF
PDF byte limits are separate from ordinary-page limits. `pypdf` extracts bounded page text and metadata. PDF content enters the same snapshot/evidence pipeline.

### Citation snowballing
DOI, arXiv and public URL references become explicit citation records and high-value frontier leads. A citation is a lead, not automatically evidence.

## 5. Stage 5 foundation

Graph state is intentionally grounded in claims rather than raw model inference.

- Entity normalization may use a model.
- A relationship is accepted only if it references a claim ID already stored in the run.
- Invalid/unknown claim IDs are rejected.
- Timeline events come from grounded claim dates.
- Every relationship/timeline item retains claim/source provenance.

SQLite is sufficient at this stage. A dedicated graph database is deferred until query volume/graph size justifies the operational cost.

## 6. Frontier

Recursive browsing is best-first and budgeted, not naive depth-first explosion. Frontier entries carry URL, parent source, relation, depth, score and lease status. The run can recover stale leases after restart.

## 7. TUI architecture

The TUI has two visual states:

- **Landing:** centered input, folder, planning route/model, random tip.
- **Workspace:** live Markdown report + compact focus/gaps + evidence table + bounded activity trace + moving status/token indicator.

The prompt is borderless except for one colored quote line. Typing `/` opens a clickable command palette. No Footer widget
is used; landing centering uses Textual's `CenterMiddle` and workspace centering uses symmetric layout.

TUI sessions persist separately from research runs, so switching sessions changes operator context without destroying evidence.
Session metadata retains run IDs and the preferred deployment. The preference is only a routing bias; health/circuit state
still falls back to another token/model/provider.

## 8. Security boundaries

- Live fetch validation rejects private/link-local/internal target addresses.
- `robots.txt` is respected for normal live traversal.
- Web content is untrusted data and is never interpreted as system/tool instructions.
- The local shell is an operator convenience, disabled by default, and is not exposed to the LLM or web content.
- Specialist adapters use public APIs/public repositories/public archives; no credential harvesting or authenticated/private crawling is implemented.
- Telegram uses an operator-authorized official user session but only persists globally searchable messages that have a
  public `t.me` URL. LinkedIn is official/indexed/import only; fake-account scraping and access bypass are not implemented.
- Remote vision is globally disabled by default, requires per-run opt-in, has its own hard budget, and cannot identify a
  person from a face or analyze minors.
- The OpenAI-compatible mesh supports five credential slots per provider and three Cloudflare account pairs. Catalogs and
  health remain credential scoped; network circuits prevent one unstable gateway from exhausting every model retry.
- JS-heavy public-page fallback can rotate Cloudflare Browser Rendering `/markdown` accounts before loading a local browser.
  It never bypasses authentication, CAPTCHA, robots policy or private-network validation.

## 9. Extension points

Future stages can add adapters without changing the core evidence model:

- additional public registries and structured datasets
- stronger entity resolution/source-family analysis
- archive-diff engine
- GraphRAG/corpus community summaries
- distributed workers/Redis/PostgreSQL when one-node SQLite becomes a bottleneck
- richer TUI graph/timeline views
- typed allowlisted MCP source adapters. Arbitrary MCP tools are not exposed to the model because a server may contain
  mutating, private-data or active-network capabilities.
