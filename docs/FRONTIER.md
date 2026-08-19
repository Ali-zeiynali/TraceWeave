# Best-first research frontier

## Why not crawl every link to depth five?

Naive depth traversal grows combinatorially and wastes bandwidth on navigation, privacy pages, calendars and duplicate content. TraceWeave uses depth as a hard ceiling while priority and budget determine what is actually visited.

## Candidate inputs

A fetched HTML page contributes:

- ordinary hyperlinks
- citation/document-like hyperlinks
- RSS/Atom feed links
- bounded sitemap candidates

Each frontier record stores the parent source, relation, anchor text, depth, canonical URL, domain, score and durable status.

## Score

Stage 3's deterministic scorer uses:

- lexical overlap with topic + angle
- anchor text
- URL path
- same-domain context
- citation/report/document signals
- low-value path penalties
- mild depth penalty

This is intentionally deterministic and cheap. Future versions can add a model reranker only for ambiguous/high-impact batches.

## Durable states

```text
pending → leased → completed
                 ↘ failed
```

On resume, abandoned `leased` records are returned to `pending` so a process crash cannot permanently lose frontier work.

## Budgets

A run has:

- `max_depth` 0..5
- total `max_frontier_pages`
- minimum score
- per-domain completed-page limit
- global fetch concurrency

The total budget is distributed across plan/search rounds so early discovery does not consume the whole run before later re-plans generate better leads.

## Browser fallback

Normal HTTP collection remains the default. If enabled and an HTML page produces too little text, TraceWeave may try Crawl4AI and keep the richer result. This path is optional because browser processes consume much more memory.
