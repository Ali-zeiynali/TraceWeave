# Changelog

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
