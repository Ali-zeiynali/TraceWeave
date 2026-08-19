# Patch Notes — v0.3 → v0.5

This patch is an in-place, additive upgrade. It preserves `.env`, `providers.toml`, `.git`, and `.traceweave` durable data.

## Added

- Stage 4: Wayback, Common Crawl, OpenAlex, Crossref, arXiv, GitHub public search, PDF parsing, citation snowballing.
- Stage 5 foundation: entity, relationship, timeline and research-edge tables plus grounded GraphCurator.
- Built-in provider presets for AgentRouter, SeekRouter, ZenMux, OpenRouter, Mistral, Gemini and Groq.
- Up to three environment credentials/provider.
- Credential-scoped dynamic model catalogs.
- Periodic catalog refresh + per-token catalog retry backoff + async refresh lock.
- Redesigned minimal TUI landing using Textual `CenterMiddle`; no `margin: auto`, no Footer.
- Archive/citation/entity/timeline inspection commands and richer JSON/Mermaid exports.
- Stage-4/5 integration smoke test.

## Router behavior changed

- 401/402/429 affect credential health.
- 403 is treated as model/request/deployment scoped rather than automatically poisoning the credential.
- refusal and JSON-format failures are task scoped.
- catalog availability may differ across tokens on the same provider.

## Backup behavior

The PowerShell patch creates a timestamped backup directory before replacing files. Existing TraceWeave DB/WAL/SHM files are copied there before migration.

## Dependencies

Stage 4 installs `pypdf`. Browser/Crawl4AI and LiteLLM remain optional extras.
