# TraceWeave roadmap

## v0.1 — Research Core ✅

- TUI/CLI
- iterative plan/search/re-plan
- search provenance
- HTTP snapshots
- SQLite resume
- source inventory exports

## v0.2 — Evidence & Triage ✅ (included in v0.3 patch)

- relevance / importance / novelty / authority
- exact and near duplicate detection
- source-family foundation
- grounded atomic claims
- exact evidence spans
- evidence export
- task-specific prompts
- progressive skill-loading foundation

## v0.3 — Deep Traversal + Provider Mesh ✅

- best-first durable frontier
- recursive link discovery with depth ceiling
- page budget and per-domain limits
- sitemap + feed discovery
- robots policy
- optional Crawl4AI fallback
- sessions and improved onboarding TUI
- provider/token/model router
- dynamic cooldown and failover
- LiteLLM optional driver
- command history/autocomplete/local shell

Provider routing was moved forward from the earlier v0.6 concept because long-running free/credit-based research depends on it from the beginning.

## v0.4 — Archives & specialist sources

- Wayback Machine adapter
- Common Crawl index/WARC retrieval
- robust PDF parsing and document metadata
- OpenAlex / Crossref / arXiv adapters
- citation snowballing
- historical snapshot diffing

## v0.5 — Graph intelligence

- explicit Research Graph separate from Knowledge Graph
- entity normalization/resolution
- typed relationships
- timelines
- contradiction records
- novelty lead records
- graph-aware retrieval

## v0.6 — Provider intelligence expansion

- quota header normalization per provider
- provider-specific daily/reset windows
- usage reservations by task class
- task-history learned routing
- optional local model pools
- model capability probing command (not a mandatory benchmark lab)

## v0.7 — Long memory & skill ecosystem

- branch notebooks
- compact context builder
- retrieval over branch/evidence memory
- external skill packages
- skill permissions
- checkpoint compaction for very long runs

## v0.8 — Specialist public OSINT adapters

- GitHub repository/issues/commit history
- RDAP / DNS / certificate-transparency / ASN passive enrichment
- public corporate registries adapters
- media/OCR provenance
- bounded public-asset relationship mapping

## v0.9 — QA & observability

- citation auditor
- coverage auditor
- source-independence inference
- contradiction hunter
- OpenTelemetry traces
- provider outage/429/refusal chaos tests
- hidden-breadcrumb benchmark

## v1.0 — Research OS

- stable plugin/skill/provider interfaces
- Quick / Standard / Deep / Exhaustive policies
- graph/timeline/evidence views in TUI
- production migration tooling
- multi-worker queue option
- documented API service
- comprehensive evaluation suite
