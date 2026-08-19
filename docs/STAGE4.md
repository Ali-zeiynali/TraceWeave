# Stage 4 — Specialist Sources and Historical Evidence

## Goal

Stage 4 makes TraceWeave capable of finding evidence that normal search loops often miss, while preserving the same source/provenance invariants.

## Adapters

### Wayback Machine
Uses the CDX endpoint to request successful captures, collapse duplicate digests, and select captures spread across time. Captures are stored with original source ID, timestamp, digest, MIME/status and capture URL. Wayback pages are also materialized as normal `archive` sources so they can pass through fetch → triage → claim extraction.

### Common Crawl
Uses the current Common Crawl index metadata, queries the CDXJ index, records selected historical captures, and range-fetches bounded WARC records. Raw/text historical payloads are stored separately from the live source.

### OpenAlex
Finds works and keeps canonical work/DOI metadata, dates and citation counts where supplied by the public API.

### Crossref
Adds DOI/publisher/bibliographic coverage independent of OpenAlex.

### arXiv
Adds canonical arXiv records and abstracts through the public Atom API.

### GitHub
Searches public repositories and issues. This is research-source discovery, not repository modification.

### PDF
PDF responses are bounded by `TRACEWEAVE_PDF_MAX_BYTES`. `pypdf` extracts at most 500 pages of text and title metadata. No OCR is attempted in v0.5.

## Citation snowballing

The citation parser extracts:

- DOI references → `https://doi.org/...`
- arXiv identifiers → canonical arXiv URLs
- public HTTP(S) references

Each reference becomes a citation record plus a scored frontier lead. It still must be fetched and evaluated before it can support a claim.

## Resume behavior

Archive work is keyed by `(run, source, stage)`:

- `archive:wayback`
- `archive:commoncrawl`

Completed work is not repeated on later rounds/resume. Error state remains retryable.

## Resource policy for an 8 GB VPS

The default Stage-4 adapters are light relative to browser rendering. Recommended:

- HTTP fetch concurrency: 4
- browser fallback: off initially
- archive sources/round: 4
- captures/source: 3
- specialist query families/round: 3
- specialist results/query: 5

Increase breadth before increasing browser concurrency.
