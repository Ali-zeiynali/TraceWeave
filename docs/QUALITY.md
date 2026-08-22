# Engineering and release quality

TraceWeave avoids “AI slop” by making product claims auditable. A named capability is integrated only when all of these exist:

1. a bounded typed adapter or internal interface;
2. explicit inputs, timeouts, budgets, and failure behavior;
3. source/snapshot provenance in persistent state;
4. a contract test and, where credentials permit, a real smoke test;
5. user-facing configuration and limitation documentation.

Anything else is marked `catalog-only`, experimental, or backlog. A package name in the toolbox is not evidence of integration.

## Prompt rules

- Prompts are small and task-specific. They request structured data rather than ornamental prose.
- Web pages, documents, tool descriptions, and retrieved instructions are untrusted evidence—not instructions to the agent.
- Claims must cite stored source IDs and literal evidence spans. The model cannot manufacture a source, domain, quote, or tool result.
- Verification compares existing claims. It cannot create new evidence or upgrade one source into independent corroboration.
- Identity resolution is hypothesis generation. Name similarity is insufficient; a `same` verdict requires at least two grounded claims from two domains.
- Reports preserve uncertainty, counter-evidence, failed searches, and unresolved gaps. Prompts do not force a predetermined conclusion.
- The synthesis model returns claim/observation ID groupings only. TraceWeave renders factual lines, quotes, source IDs, and verdicts deterministically from SQLite.
- Remote vision reports visible observations. It does not infer sensitive traits or identify a person from a face.

## Writing rules

Public documentation and generated reports should be specific: name the adapter, data boundary, command, date, limitation, and failure mode. Avoid generic superlatives, feature dumping, repetitive section templates, fake completeness, and claims such as “production ready” without a corresponding release gate. Changelog entries describe observable behavior, not aspirations.

## Release gates

For a tagged release:

- `ruff check src tests scripts` and `ruff format --check src tests scripts` pass;
- the deterministic suite passes without network access;
- CLI version, doctor, export, resume, and TUI layout smoke checks pass;
- schema upgrades open an old database without losing evidence;
- configured provider and public-source smoke tests record status without printing credentials;
- benchmark cases include company/infrastructure, multilingual, contradiction, and sparse-evidence prompts;
- generated reports are checked for source IDs, literal quotes, independent-domain assessments, uncertainty, and unsupported identity joins;
- package metadata, examples, changelog, security policy, and known limitations agree on the shipped version;
- a secret scan confirms that test artifacts and documentation contain no credential values.

Network smoke tests are evidence for a release candidate, not deterministic unit tests: third-party quotas, indexes, and APIs can change independently of TraceWeave.
