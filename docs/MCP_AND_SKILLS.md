# MCP and Agent Skills

TraceWeave supports project-local skills and conservative MCP interoperability. Neither mechanism grants retrieved content authority over the host.

## Agent Skills

Skills are discovered from:

- `.traceweave/skills/catalog.toml`;
- `.agents/skills/<name>/SKILL.md`;
- `.opencode/skills/<name>/SKILL.md`;
- `.claude/skills/<name>/SKILL.md`.

A `SKILL.md` file is visible to the operator by default. To opt it into automatic task prompting, add frontmatter such as:

```yaml
---
name: company-research
description: Evidence-first public company research.
traceweave-tasks: planning, replanning, synthesis
---
```

Only the listed task prompts receive the skill. Run `traceweave skills` or `/skills` to inspect scope and origin. Skills cannot invoke shell commands or convert web-page instructions into agent instructions.

## MCP configuration

Copy `mcp.example.toml` to `.traceweave/mcp.toml` and use HTTPS endpoints (plain HTTP is accepted only on loopback):

```toml
[[servers]]
name = "public-research"
url = "https://example.org/mcp"
allowed_tools = ["search", "fetch_public_record"]
timeout_seconds = 20
```

`traceweave mcp --server public-research` performs the MCP initialize lifecycle and paginated `tools/list`, then shows which tools are allowlisted. The client implements the stable 2025-11-25 Streamable HTTP protocol and preserves the negotiated session ID when a server uses sessions.

Calling a tool requires an exact `allowed_tools` match. The current research engine does not autonomously execute discovered MCP tools; integrations must convert returned records into TraceWeave provenance before they can become evidence. This keeps MCP useful for inspection and typed extensions without treating every remote capability as safe or public.

Secrets belong in environment variables or an operator-managed gateway, not in committed TOML. `mcp.example.toml` contains no credentials.
