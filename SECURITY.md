# Security Policy

TraceWeave processes untrusted public-web content and should be treated as a network-facing research tool.

## Supported version

During the 0.x series, only the newest release receives fixes.

## Reporting a vulnerability

Please report security issues privately to the repository maintainers rather than posting exploit details in a public issue. Replace this paragraph with your project security contact before publishing the repository.

## Stage-1 security boundaries

- Only HTTP/HTTPS fetching is supported.
- Private, loopback, link-local and other non-global IP destinations are rejected.
- Redirect targets are validated before following them.
- Response bytes and request duration are bounded.
- Unsupported binary content is not parsed in Stage 1.
- Web content is data; it is never allowed to modify system prompts or execute tools by itself.
- LLM credentials are read from environment configuration and are not intentionally written to the run database.

These controls reduce risk but are not a formal sandbox. Run TraceWeave under a normal unprivileged OS account and keep secrets unrelated to research outside its process environment.

## Authorized use

TraceWeave is intended for lawful public-source research. Do not use it to bypass authentication/access controls or to test systems without authorization. Active network probing, when added later, should remain explicitly scoped and disabled by default.
