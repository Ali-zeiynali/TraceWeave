# TraceWeave 1.0.2 release notes

Version 1.0.2 is the first public-release candidate of the evidence-first research agent. It upgrades the existing architecture instead of replacing its storage, engine, source-manager, router, or TUI foundations.

## Shipped

- Lead-agent reconciliation on top of bounded specialist branches.
- Structured lead-agent report organization; factual report lines are rendered from persisted evidence IDs rather than model-authored facts.
- Persisted independent-domain claim assessments used by synthesis and exports.
- Conservative person-resolution hypotheses and non-biometric image duplicate matching.
- Passive organization/infrastructure adapters for DNS, CT, RDAP, RIPEstat, PeeringDB, SEC index, Companies House, and urlscan.
- Paid opt-in OpenAI, DeepSeek, xAI, Together, and Fireworks presets alongside existing free-tier routes and custom OpenAI-compatible providers.
- Agent Skills compatibility, MCP discovery/allowlists, stronger CLI inspection, and a simpler TUI.
- Honest toolbox states, release-quality guidance, and expanded deterministic/real evaluation paths.

## Known limits

- TraceWeave does not bulk-scrape authenticated LinkedIn, capture session cookies, bypass login/CAPTCHA controls, or traverse private connections. It can use approved official APIs, indexed public pages, and future typed imports of operator-owned exports.
- Perceptual hashes find identical or near-duplicate images; they do not prove that two photographed people are the same person. Person joins remain evidence hypotheses.
- MCP support covers secure Streamable HTTP discovery and explicit calls. Discovered tools are not automatically added to autonomous research plans.
- SEC asks operators to set a descriptive `SEC_USER_AGENT`; the adapter remains disabled until it is present.
- Cloudflare Browser Rendering and local browser fallback are optional extraction paths, not access-control bypasses.
- Free tiers and public indexes are external services. Availability, limits, completeness, and terms can change.
- Active scanning, exploit/vulnerability probing, credential testing, reset-side-channel enumeration, and evasion are outside the product boundary.

See `docs/QUALITY.md` for release gates and `docs/MCP_AND_SKILLS.md` for extension boundaries.

The source distribution includes the complete documentation set plus `.env`, provider, and MCP examples; the wheel includes all runtime prompts and built-in skills.
