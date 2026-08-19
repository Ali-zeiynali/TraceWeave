# v0.1 → v0.3 Patch Notes

This release intentionally applies Stage 2 and Stage 3 together.

## Preserved by the patch

- `.traceweave/` research database, snapshots, exports and sessions
- `.env`
- `.git/`
- an existing `providers.toml`

Files that the patch replaces are copied to `.traceweave-patch-backup/<timestamp>/` before overlay.

## Additive database migration

The v0.3 storage initializer keeps all v0.1 core tables and adds columns/tables for evidence, frontier, sessions and router health. The migration tests construct a v0.1-style database and initialize it with the v0.3 storage layer.

A filesystem backup is still recommended before any software upgrade.

## Important behavior changes

- Deep mode defaults to 4 plan/search rounds.
- Stage 3 recursive traversal is best-first and budgeted rather than exhaustive breadth crawling.
- Models no longer need tool calling.
- Provider routing is `provider + token + model`, with narrower task health for refusals/format failures.
- Search provenance remains stored before fetch.
- The TUI footer is removed; initial empty panes are hidden behind onboarding.
- Local shell is available but disabled by default.

## Optional dependencies

The base patch stays light. Use patch switches or install extras later:

```bash
pip install -e '.[providers]'   # LiteLLM driver
pip install -e '.[browser]'     # Crawl4AI
pip install -e '.[full]'        # both
```
