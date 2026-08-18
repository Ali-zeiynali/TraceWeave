# Contributing

Thanks for improving TraceWeave.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate          # Linux/macOS
# .\.venv\Scripts\Activate.ps1   # Windows PowerShell
python -m pip install -U pip
pip install -e '.[dev]'
cp .env.example .env              # Copy-Item on PowerShell
```

Before a pull request:

```bash
python -m compileall -q src tests
ruff check src tests
pytest
python scripts/smoke_test.py
```

## Design rules

1. Durable research state must not live only inside model context.
2. Search discovery provenance must survive fetch/parser/model failure.
3. A model provider must be replaceable without rewriting research orchestration.
4. High-volume deterministic work should not become LLM calls.
5. New source adapters return normalized records instead of leaking provider-specific shapes throughout the codebase.
6. Public-web content is untrusted data, never executable instruction.
7. Keep Stage-1 behavior lightweight on small VPS hosts.

## Pull requests

Explain:

- the problem;
- the architectural impact;
- migration/storage effects;
- tests added;
- any new network permissions or external services.

Do not include API keys, private datasets or credentials in issues, fixtures, logs or pull requests.
