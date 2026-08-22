# TraceWeave roadmap

This roadmap records shipped work separately from future work. A capability is marked delivered only when it has a typed implementation, provenance, tests, and user documentation.

## Stage 1 — trustworthy research core (v1.0.2, delivered)

- Prompt-first intent parsing, iterative planning, bounded replanning, and a lead-agent reconciliation pass.
- Quick, Standard, Deep, and Overnight budgets with persistent deadlines, resumable leased tasks, and provider failover.
- Literal-quote claims, snapshots, citations, source scoring, contradiction-aware synthesis, and independent-domain claim assessments.
- Task-aware model routing across free-tier presets and opt-in paid OpenAI-compatible providers.
- SQLite case state, JSON/Markdown/evidence-matrix/Mermaid/GraphML exports, and reproducible run workspaces.

## Stage 2 — OSINT depth and analyst precision (v1.0.2, delivered)

- Passive DNS (A/AAAA/CNAME/MX/NS/TXT/CAA/SOA), RDAP, Certificate Transparency, RIPEstat, PeeringDB, GLEIF, ROR, ORCID, SEC company index, Companies House, and urlscan search.
- Public web, archives, publications, code, news, social-index leads, media collection, OCR, metadata, perceptual-image matching, and optional bounded remote vision.
- Four specialist research branches with lead-agent plan reconciliation and evidence-aware synthesis.
- Conservative person-resolution hypotheses that require grounded evidence from independent domains; image hashes identify duplicate artifacts, not people.
- Agent Skills discovery from `.agents`, `.opencode`, and `.claude`, plus existing TraceWeave project skills.
- MCP 2025-11-25 Streamable HTTP discovery and explicitly allowlisted calls. MCP tools are not granted autonomous authority.
- A capability catalog that labels unimplemented local/third-party tools as `catalog-only` instead of pretending they are integrated.

## Stage 3 — public product and operations (v1.0.2, delivered)

- Simplified full-screen onboarding, vertically corrected input fields, live report/evidence/graph/timeline/verification/identity views, and operational slash commands.
- CLI inspection for providers, sources, toolbox, skills, MCP, verification, identity, exports, resume, and diagnostics.
- Public-use defaults: passive collection, SSRF protections, robots handling, prompt-injection boundary, no CAPTCHA bypass, no credential testing, and no arbitrary model-composed shell.
- Release documentation, environment examples, migration-safe schema creation, quality gates, and an end-to-end evaluation harness.

## Post-1.0 backlog

- Numbered forward-only migration files replacing compatibility `_ensure_column` upgrades.
- Source-family/syndication clustering, archive diffs, stronger temporal reasoning, and explicit citation-to-target resolution.
- Durable per-fetch/per-analysis work units for distributed workers; a single-node install remains the default.
- OpenTelemetry-compatible traces, provider-chaos tests, crash/restart endurance runs, and a larger frozen public benchmark corpus.
- Typed adapters for selected catalog-only CLIs and operator-owned LinkedIn data exports, after contract and provenance tests exist.
- Optional standards-compliant MCP stdio bridge without exposing arbitrary subprocess execution to fetched content or models.
