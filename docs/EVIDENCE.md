# Evidence model

TraceWeave stores discovery, documents, analysis, claims and evidence separately.

## Discovery is not evidence

A search result is stored immediately so the lead is durable, but a snippet is not automatically considered factual evidence.

`run_sources` preserves every discovery path while `sources` deduplicates the canonical URL.

## Snapshot

A successful fetch stores:

- final URL
- HTTP status
- content type
- SHA-256
- raw gzip-compressed body
- extracted text
- extracted title
- 64-bit SimHash
- retrieval time

## Triage

Each run/source pair can receive:

- relevance
- importance
- novelty
- authority
- rationale
- topics
- research leads
- duplicate source id
- source-family key

The scores are dimensions, not one magic truth score. A source can be highly important but low authority, or authoritative but irrelevant to the current angle.

## Duplicate handling

Exact raw content uses SHA-256. Near duplicates use SimHash Hamming distance. When a near duplicate is found, novelty is capped and `duplicate_of` is stored.

This is a first foundation for source independence. Later stages can infer syndication/citation lineage rather than treating every near-duplicate domain as independent confirmation.

## Claims

LLM claim extraction is optional. A proposed claim contains an exact `evidence_quote`. Before persisting it as grounded evidence TraceWeave searches the stored source text for the exact substring and records character offsets.

If the quote cannot be located, that claim is discarded by the current Stage-2 grounding gate.

## Export

```bash
traceweave export RUN_ID --format evidence
```

produces an evidence matrix. Full JSON contains sources, discoveries, claims, frontier state and events.
