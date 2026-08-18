# TraceWeave Roadmap: 0.1 → 1.0

The project is staged so every milestone remains usable. Features move forward only after the previous foundation is stable.

## v0.1 — Research Core (current)

**Goal:** a small research program that is already useful rather than a demo.

- Textual TUI + Typer CLI.
- ResearchSpec: topic, angle, mode, rounds, language.
- iterative plan/search/re-plan loop.
- SearXNG + DDGS search abstraction.
- OpenAI-compatible optional planner.
- SQLite durable state.
- full search-result provenance.
- safe bounded text/HTML fetching.
- raw snapshot + extracted text storage.
- run history, resume and export.
- tests and open-source repository foundation.

**Exit criterion:** two-round offline integration test passes; an interrupted run can retain plan/query/source state; exports identify how each source was found.

## v0.2 — Evidence & Triage

**Goal:** stop treating a collection of pages as research knowledge.

- deterministic and semantic deduplication.
- document/chunk model.
- source-quality metadata.
- relevance, novelty and importance scores.
- claim extraction.
- evidence spans linked to source snapshots.
- citation IDs stable across exports.
- source-family/syndication hints.
- first evidence matrix.

**Exit criterion:** a generated claim can be traced to an exact stored source passage; duplicated/syndicated pages do not dominate the output.

## v0.3 — Frontier & Deep Traversal

**Goal:** move beyond normal search results.

- URL frontier.
- semantic best-first traversal.
- bounded recursive link following.
- per-domain budgets and delays.
- sitemap and RSS discovery.
- link-edge types and discovery reasons.
- Crawl4AI integration for JS pages.
- optional Playwright browser fallback.
- backpressure and worker leasing.

**Exit criterion:** a run can follow useful links several hops deep without breadth explosion or unbounded browser usage.

## v0.4 — Archives, Documents & Academic Sources

**Goal:** recover information that normal current-web search misses.

- Wayback Machine adapter.
- Common Crawl index/capture adapter.
- archived-page diffing.
- PDF/document pipeline.
- OpenAlex/Crossref/arXiv adapters.
- backward/forward citation chasing.
- reference resolver.
- historical-source priority rules.

**Exit criterion:** hidden-breadcrumb benchmark can reach an answer requiring an archived/dead source or a cited paper.

## v0.5 — Research Graph & Knowledge Graph

**Goal:** represent both the investigation process and discovered knowledge.

- separate Research Graph and Knowledge Graph.
- entity extraction/resolution.
- relationship edges with evidence.
- timeline as a first-class structure.
- novelty lead generation.
- contradiction records.
- graph-aware retrieval.
- GraphRAG-style corpus analysis as an optional post-processing layer.

**Exit criterion:** users can answer both “what is related to X?” and “why did the agent investigate X?” from stored graph state.

## v0.6 — Model & Provider Mesh

**Goal:** survive unstable/free endpoints without coupling research logic to one model.

- capability profiles per endpoint/model.
- task pools: cheap JSON, multilingual, reasoning, vision, synthesis, etc.
- provider health and rolling failure metrics.
- quota/rate metadata.
- refusal/error classification.
- structured-output validation and repair.
- provider fallback without changing research nodes.
- LiteLLM integration where it reduces connector work.
- models without tool calling remain first-class workers.

**Exit criterion:** killing or refusing one provider mid-run does not destroy the run; compatible work is re-routed and provenance records which model did what.

## v0.7 — Skills, Context & Long-Horizon Memory

**Goal:** run for hours without carrying the entire investigation in model context.

- progressive skill loading.
- branch notebooks.
- working-memory builder.
- branch summaries distinct from evidence.
- context budgets per role/task.
- checkpoints around expensive steps.
- stronger idempotency.
- research convergence scoring.
- gap/coverage controller.

**Exit criterion:** a multi-hour run can restart and continue without chat-history reconstruction and without linearly growing prompts.

## v0.8 — Specialist Public-OSINT Adapters

**Goal:** broaden public-source research beyond pages and papers.

- GitHub/GitLab/public code research.
- RDAP and DNS.
- Certificate Transparency metadata.
- ASN/BGP/public infrastructure relationships.
- passive asset discovery adapters.
- public corporate/filing connectors by jurisdiction.
- media discovery, OCR and perceptual duplicate clustering.
- specialist source-quality rules.

Active network testing remains a separate, authorization-gated capability rather than a default research tool.

**Exit criterion:** specialist data enters the same evidence/provenance model instead of being dumped as unrelated tool output.

## v0.9 — Quality, Evaluation & Observability

**Goal:** know whether the system is good rather than merely impressive-looking.

- hidden-breadcrumb benchmark.
- primary-source recall.
- obscure-source recall.
- archive discovery rate.
- contradiction detection.
- entity-resolution accuracy.
- unsupported-claim rate.
- source-independence accuracy.
- cost/tokens per verified claim.
- provider failover tests.
- restart/resume chaos tests.
- OpenTelemetry tracing.
- trace/research-graph visualization data.
- citation auditor and coverage auditor.

**Exit criterion:** regressions are measurable and long runs can be debugged from traces/events without replaying them manually.

## v1.0 — Research OS

**Goal:** stable extensible product boundary.

- Quick / Standard / Deep / Exhaustive modes.
- stable plugin/adapter/skill interfaces.
- migrations and backward-compatible run format.
- polished TUI with command palette, branch navigation, graph/timeline views and source inspector.
- provider mesh.
- specialist adapters.
- evidence-grounded reports.
- research graph + knowledge graph exports.
- reproducible packaged releases.
- deployment and security hardening documentation.

**1.0 principle:** the model is a replaceable reasoning component. Sources, evidence, state, graph, policy, recovery and provenance belong to TraceWeave itself.
