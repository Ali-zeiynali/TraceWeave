# Security Policy

## Supported scope

TraceWeave v0.5 is a public-research tool. Supported collection includes ordinary public web pages, public archives, public academic metadata, public GitHub data and public documents.

It is not designed to bypass authentication, CAPTCHAs, paywalls, access controls, robots policy, or network authorization boundaries.

## Web-content trust

Fetched HTML/PDF/archive content is untrusted data. Instructions embedded in sources do not override TraceWeave prompts/policies and do not trigger local tools.

## SSRF / network boundary

The ordinary fetcher validates destinations and rejects local/private/link-local addresses. Do not weaken this boundary when adding source adapters.

## Local shell

The TUI shell is disabled by default and is an operator-only convenience. It is never exposed as an LLM tool. Commands execute with the OS permissions of the TraceWeave process.

## Secrets

- Put API tokens in `.env`, service environment variables, or your secret manager.
- Do not put raw tokens in `providers.toml`.
- Model catalog and router health state store credential IDs only.
- `.env` and `.traceweave/` are ignored by Git.

## Personal data

Do not extend TraceWeave to infer/aggregate private-person precise routines, private contact details, credentials, private addresses or sensitive attributes from weak breadcrumbs. Public professional-role research should remain proportionate to the research purpose.

## Reporting issues

For a public repository, use a private security-advisory channel rather than opening a public issue with exploitable details or real secrets.
