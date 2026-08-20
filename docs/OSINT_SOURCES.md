# Passive OSINT sources and policy

TraceWeave exposes source integrations through typed adapters and a visible capability catalog (`traceweave toolbox`).
The autonomous engine may call passive/public adapters; it may not turn model output or fetched text into arbitrary shell
commands. Stability describes the integration surface, not the truth of an individual record.

## Stable, no-auth APIs

| Source | Coverage | Current behavior |
|---|---|---|
| ICANN/RDAP bootstrap | domain/IP registration | Exact domains found in a query become registry sources. Prefer RDAP over legacy WHOIS. |
| Cloudflare DNS-over-HTTPS | current DNS answers | Passive resolution only; no port scan or service probing. |
| RIPEstat | ASN/prefix/routing context | Exact IP resources become network-registry sources. |
| GLEIF | LEI/legal entities | Full-text company discovery with raw record provenance. |
| ROR | research organizations | Organization candidates and canonical ROR IDs. |
| ORCID public API | researcher candidates | Candidate discovery only. A name-only hit is never auto-merged into a person. |
| SEC EDGAR | US filings | Cataloged for a typed CIK/filing adapter; no key required. |
| OpenAlex/Crossref/arXiv | publications/citations | Existing specialist adapters. |
| Bluesky public AppView | public posts | Deep/Overnight search through the public `searchPosts` endpoint. |
| Wayback/Common Crawl | historical public web | Time-scoped captures, separately preserved from current pages. |

Official references: [ICANN RDAP](https://www.icann.org/rdap/), [RIPEstat](https://stat.ripe.net/docs/),
[GLEIF API](https://www.gleif.org/en/lei-data/gleif-api/), [SEC data APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces),
[ROR API](https://ror.readme.io/docs/rest-api), [ORCID public API](https://info.orcid.org/documentation/features/public-api/),
[Bluesky API](https://docs.bsky.app/docs/api/app-bsky-feed-search-posts).

## Stable APIs needing a token/account

| Source/provider | Variables | Notes |
|---|---|---|
| GitHub public API | `TRACEWEAVE_GITHUB_TOKEN` | Optional; raises normal public API limits. |
| Companies House | `COMPANIES_HOUSE_API_KEY` | Free key; normal service rate limits apply. |
| urlscan | `URLSCAN_API_KEY` | Existing public scan search only. TraceWeave does not submit scans. |
| Telegram official user API | `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION_PATH` | Enable with `TRACEWEAVE_TELEGRAM_PUBLIC_ENABLED=true`. Authorize once interactively. Only globally searchable messages with a public `t.me` URL are retained. |
| Instagram Graph API | `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_USER_ID` | Official professional-account hashtag discovery only; enable explicitly. It is not a general people-search API. |
| LinkedIn official APIs | `LINKEDIN_ACCESS_TOKEN` | Product approval is restricted and does not provide unrestricted employee/activity search. |

Telegram uses the official user method `messages.searchGlobal`; it does not read private groups, contacts, private dialogs,
or bypass membership. See [Telegram’s method reference](https://core.telegram.org/method/messages.searchGlobal).
After setting the variables, run `pip install -e '.[social]'` and `traceweave telegram-login` once interactively, then enable
`TRACEWEAVE_TELEGRAM_PUBLIC_ENABLED=true` for unattended public searches.

LinkedIn’s official Profile API is restricted and LinkedIn limits storage/use of other-member data. TraceWeave therefore has
three allowed paths: approved official APIs, public pages found by normal search engines, and user-provided exports. It does
not implement fake-account scraping, session-cookie capture, CAPTCHA bypass, proxy rotation, or bulk traversal of private
connections. See [LinkedIn Profile API](https://learn.microsoft.com/en-us/linkedin/shared/integrations/people/profile-api).

## Search and social surfaces with unstable coverage

- SearXNG is the preferred self-hosted search layer. DDGS remains a zero-key fallback whose upstream behavior can change.
- Public indexed `site:linkedin.com/in`, `site:linkedin.com/posts`, `site:instagram.com`, and `site:t.me` queries are added in
  Deep/Overnight fallback plans. Indexed coverage is incomplete and fetchability can change.
- Mastodon coverage is instance/federation dependent and remains cataloged but is not treated as a global search API.
- Brave Search is not integrated as a default because its current access is not a dependable unrestricted zero-cost API.
- Jina Reader (`r.jina.ai`) is suitable as a future text-extraction fallback, but its public no-key endpoint is quota-limited;
  it is not treated as an always-available search index. A free Jina key is useful if the operator later enables Search/MCP.

Google Custom Search is intentionally not a new default: Google closed it to new customers and announced a January 2027
sunset. GitHub Models is also not a provider target because the service was retired on July 30, 2026.

## Local deterministic tools

`traceweave toolbox` detects Sherlock, Maigret, SpiderFoot, theHarvester, Amass, Subfinder, WHOIS, dig, Tesseract,
ImageHash, optional OpenCV, ExifTool and ffprobe. CLI entries remain capability declarations unless a typed adapter is
implemented; fetched content cannot invoke raw shell. SpiderFoot/theHarvester/Amass/Subfinder are cataloged only for
passive source profiles. ExifTool, Tesseract, ImageHash and OpenCV are invoked through fixed deterministic media paths,
with bounded input/output rather than model-composed commands.

Holehe and password-reset enumeration are intentionally excluded. Active port scanning, vulnerability probing, credential
testing, password-reset side channels, and evasion/rotation mechanisms are outside the passive-data product boundary.

## Media and vision

Deep/Overnight runs extract `og:image` and public `<img>` leads, download bounded raster formats, content-address them by
SHA-256, and connect them to source/snapshot/artifact/observation graph nodes. The local-first stack extracts ExifTool
metadata, multilingual Tesseract OCR, ImageHash perceptual fingerprints and optional OpenCV dimensions/quality/edge
metrics before any remote vision call. Important artifacts are copied or hard-linked into each case workspace. No face
identity model is loaded.

For JS-heavy public pages, `TRACEWEAVE_BROWSER_BACKEND=auto` first tries configured Cloudflare Browser Rendering `/markdown`
and falls back to local Crawl4AI only when installed. Three Cloudflare account pairs are rotated under their normal account
quotas; no CAPTCHA, login wall or access control is bypassed.

Remote vision requires both:

1. `TRACEWEAVE_REMOTE_VISION_ENABLED=true`; and
2. per-run `--allow-remote-vision --max-vision-calls N` (or `/vision on` in the TUI).

The vision contract returns normalized bounding boxes, confidence, importance and rarity. It forbids face-based identity,
sensitive-trait inference and analysis of minors. Visual observations remain observations until corroborated by another source.
There is no stable unrestricted zero-cost reverse-image API; TraceWeave supports in-corpus SHA-256 matching and treats
external reverse-image result pages as user-provided imports.

## Provider free-tier matrix

Built-in token-ready routes: Groq, Gemini, Mistral free mode, OpenRouter free router, Cerebras free tier, SambaNova free tier,
Cloudflare Workers AI, NVIDIA NIM, NaraRouter, AIGate, plus the existing community routers. NVIDIA access may depend on the
model/account rather than a permanent free allowance; Nara catalogs are entitlement-scoped; AIGate is classified unstable.
Set `TRACEWEAVE_ZERO_COST_ONLY=true` to reject explicitly paid models. “Free-tier eligible” cannot prove that billing is
disabled on the operator’s account; disable paid upgrades and monitor provider dashboards.

Cloudflare requires `CLOUDFLARE_API_KEY` and `CLOUDFLARE_ACCOUNT_ID`. Only `@cf/*` Workers AI models are preset because
third-party AI Gateway routes can be billed. Official references:
[Cloudflare OpenAI compatibility](https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/),
[Cerebras free limits](https://inference-docs.cerebras.ai/support/rate-limits),
[SambaNova limits](https://docs.sambanova.ai/docs/en/models/rate-limits),
[Groq limits](https://console.groq.com/docs/rate-limits),
[Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing),
[OpenRouter free router](https://openrouter.ai/docs/guides/routing/routers/free-router).

## Skills and MCP extensions

Built-in skills are selected per task so unrelated instructions do not consume context. Operators can hot-load project skills
from `.traceweave/skills/catalog.toml`; `traceweave skills` shows origin, task scope and enabled state. The bundled web-content
firewall treats fetched instructions as evidence, never as agent commands, and the verification skill requires source-bound
claims.

Arbitrary MCP execution is not enabled in this release. An MCP server can expose mutating, private or active tools, so adding
one safely requires a typed public-data adapter, explicit tool allowlist, argument schema validation, time/budget limits and
provenance conversion. This remains a roadmap item rather than silently granting every MCP server agent authority.
