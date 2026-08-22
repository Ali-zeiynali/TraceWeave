# Changelog

## 1.0.2 — 2026-08-22

### Added
- Lead-agent reconciliation over parallel specialist planning branches.
- Claim assessment with independent-domain corroboration and contradiction records.
- Reviewable person-identity hypotheses and deterministic near-duplicate media matching.
- Multi-record DNS, Certificate Transparency, PeeringDB, URLScan search, Companies House and SEC/EDGAR adapters.
- Streamable HTTP MCP discovery with lifecycle negotiation, HTTPS/loopback validation and tool allowlists.
- Project Agent Skills discovery compatible with `.agents`, `.opencode` and `.claude` layouts.
- Official OpenAI, DeepSeek, xAI, Together and Fireworks provider catalog presets with paid-route gating.
- Verification and identity CLI/TUI views and export sections.

### Changed
- Reworked the onboarding screen and moved input text to a stable vertical baseline.
- Toolbox now labels non-integrated ideas as `catalog-only` instead of implying they execute.
- Free-form factual synthesis is replaced by ID-only lead-agent grouping and deterministic rendering from persisted claims, quotes, verdicts, observations, identity hypotheses, and media matches.
- In-flight route leasing and stage-aware attempt reserves prevent provider failures from starving claim extraction and final synthesis.
- Public version, package metadata and user agent are now 1.0.2.

## 0.5.0 — 2026-08-19

### Added
- Wayback and Common Crawl historical source adapters.
- OpenAlex, Crossref and arXiv academic discovery.
- Public GitHub repository/issue discovery.
- Bounded PDF parsing with pypdf.
- DOI/arXiv/public-URL citation snowballing.
- Grounded entity/relationship/timeline graph foundation.
- Research-edge provenance graph.
- Built-in seven-provider mesh with up to three credentials each.
- Per-credential dynamic model catalogs and zero-price filtering for OpenRouter/ZenMux dynamic catalogs.
- Periodic catalog refresh and isolated refresh backoff.
- Minimal centered TUI landing and compact workspace.

### Changed
- Provider config types separated from presets to prevent circular imports.
- Model/request 403 failures are deployment scoped.
- Re-planning receives compact archive/citation/graph/frontier state.
- Synthesis receives historical and graph context.
- Successful archive checks are durable and not repeated every round.

### Fixed
- Removed the Textual CSS `margin: auto` onboarding pattern that is not accepted by current Textual CSS.
- Preserved token health independently from model/task failures.

## 0.3.0
- Evidence/triage, best-first traversal, multi-provider/token router, sessions and durable pause/resume.
