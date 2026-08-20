# TraceWeave Roadmap

## v0.1 — Research Core ✅
TUI/CLI, iterative plan/search/re-plan, source provenance, snapshots, SQLite, resume, exports.

## v0.2 — Evidence & Triage ✅
Relevance/importance/novelty/authority, literal-quote grounded claims, near-duplicate detection, source families foundation.

## v0.3 — Deep Traversal & Provider Mesh ✅
Best-first frontier, sitemap/feed discovery, optional browser fallback, sessions, task-aware multi-token routing, dynamic cooldown, provider health.

## v0.4 — Archives & Specialist Sources ✅ (delivered in v0.5 patch)
Wayback, Common Crawl, OpenAlex, Crossref, arXiv, public GitHub, PDF parsing, citation snowballing, specialist resume state.

## v0.5 — Graph Foundation ✅
Claim-grounded entities/relationships, timeline, research edges, credential-scoped model catalogs, zero-config built-in provider presets, redesigned minimal TUI landing.

## v0.5 hardening increment ✅
- SQLite connections are transactionally closed; Windows smoke cleanup is reliable
- persistent run deadlines/model budgets and leased idempotent round tasks
- Quick/Standard/Deep/Overnight modes
- content-addressed public media and region-level observations
- opt-in remote vision with a separate budget and refusal/evasion-aware routing
- GLEIF/ROR/ORCID/RDAP/DNS/RIPEstat, Bluesky and optional official Telegram discovery
- Cerebras, SambaNova, Cloudflare Workers AI, NVIDIA text/vision, NaraRouter and AIGate presets
- five token slots per provider, three Cloudflare account pairs, usage/token dashboard and provider network circuits
- prompt-first multilingual intent parsing, no-key GDELT/MediaWiki/Hacker News fallbacks and cached public-result fallback
- project skill hot-loading plus web-content firewall and verification skills
- simplified borderless workspace pane, incremental score updates, JSON/Mermaid/GraphML exports

## v0.6 — Source Intelligence
- source-family / syndication clustering
- stronger entity resolution and aliases
- source independence score
- contradiction hunter and verification queue
- archive diff / website-change extraction
- citation resolution from citation → fetched target source
- migrate ad-hoc `_ensure_column` upgrades into fully numbered forward-only migration files
- granular durable tasks for every search/fetch/analyze operation (round tasks are durable today)

## v0.7 — Long Memory & Skills
- compact branch notebooks
- evidence-aware context builder
- skill registry metadata / progressive loading improvements (project hot-loading is delivered; version/signature policy remains)
- coverage matrix and gap prioritization
- branch saturation/convergence scoring

## v0.8 — Public OSINT Specialists
- SEC/Companies House/PeeringDB/urlscan typed adapters and Certificate Transparency history
- richer remote OCR/document tiling for public organizational material
- repository history/commit/release adapters
- typed passive CLI runners for Sherlock/Maigret/Amass/Subfinder/ExifTool/ffprobe (catalog exists; raw autonomous shell does not)
- public Mastodon adapter and operator-owned LinkedIn export importer
- typed allowlisted MCP source adapters; no arbitrary MCP tool execution or mutation authority

## v0.9 — QA / Observability
- citation auditor
- source independence auditor
- Hidden Breadcrumb research benchmark
- repeatable public `traceweave ask` benchmark artifacts and report-quality scoring (harness delivered; corpus expansion remains)
- provider-chaos tests / 429 storms / partial outage tests
- long-run crash/restart/resume benchmark
- OpenTelemetry-compatible traces and richer TUI diagnostics

## v1.0 — Research OS
- stable plugin/source/skill interfaces
- Quick / Standard / Deep / Overnight modes
- graph/timeline/evidence views in the TUI
- robust migrations and packaging
- multi-node worker option without making it mandatory for single-VPS users
- evidence-grounded final reports with explicit unresolved gaps and provenance
