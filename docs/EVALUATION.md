# Evaluation and A/B runs

The deterministic suite checks storage, budgets, routing, source contracts, MCP lifecycle, prompt boundaries, TUI layout, verification, and identity invariants. Live evaluation is separate because search indexes, provider quotas, and public APIs change.

List exact model routes:

```bash
traceweave providers --task planning --json
```

Run a bounded multilingual smoke benchmark with automatic routing:

```bash
python scripts/benchmark_agent.py --mode quick --rounds 1 --depth 0 --frontier-budget 0
```

Compare two routes while retaining automatic fallback:

```bash
python scripts/benchmark_agent.py \
  --prefer-model provider-a:token-1:model-a \
  --prefer-model provider-b:token-1:model-b \
  "Investigate the public product and infrastructure evidence for Example Corp; include counter-evidence."
```

Each matrix case stores stdout/stderr, an exported run, and a scorecard under `.traceweave/benchmarks/<timestamp>/`. Scorecards include domains, source categories, literal-span claims, report citations, official sources, model failures, claim assessments, contradictions, identity hypotheses, and summary length. They do not store API keys.

A higher numeric score is a triage signal, not proof that a conclusion is true. Review source snapshots, exact quotes, independence assessments, unsupported joins, and unresolved gaps before comparing prose quality. Do not tune a prompt to force a known answer; use a frozen scenario and judge whether the agent finds or correctly declines unsupported breadcrumbs.
