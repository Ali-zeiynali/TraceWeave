# Security policy and research scope

TraceWeave processes untrusted public-web content. Treating web pages as instructions would create prompt-injection and network-security risks, so model prompts explicitly label source content as untrusted data.

## HTTP safety

The default fetcher:

- allows only HTTP/HTTPS
- resolves hostnames and rejects private/reserved destinations
- re-checks redirected destinations
- disables ambient proxy environment inheritance for fetches
- limits response size
- limits redirects
- respects robots.txt by default

These protections are defense in depth, not a substitute for container/network isolation when running an internet-facing research service.

## Local shell

TUI shell execution is disabled by default. When enabled it is **not sandboxed**: commands run with the TraceWeave process user's operating-system permissions. Use a dedicated unprivileged service account on a VPS. Never expose a shell-enabled TUI to untrusted users.

## Secrets

Provider API tokens belong in environment variables. `providers.toml` stores environment-variable names and stable credential ids; SQLite health/attempt records store those ids but not token values.

Do not commit `.env` or token-bearing service files.

## Public OSINT scope

The default project is intended for public-web research, public documents and passive public infrastructure metadata. It should not be used to automate access-control bypass, credential theft, stalking/private-person location inference, or unauthorized active scanning.

## Reporting vulnerabilities

Please open a private security report through the hosting repository's security-advisory mechanism when available rather than publishing a working exploit in a public issue.
