from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from traceweave.utils import canonicalize_url

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
ARXIV_RE = re.compile(r"\b(?:arXiv:)?(\d{4}\.\d{4,5}(?:v\d+)?)\b", re.I)
URL_RE = re.compile(r"https?://[^\s<>\]\[\"')]+", re.I)


@dataclass(slots=True, frozen=True)
class CitationLead:
    url: str
    kind: str
    label: str


def extract_citation_leads(text: str, limit: int = 80) -> list[CitationLead]:
    out: list[CitationLead] = []
    seen: set[str] = set()
    for doi in DOI_RE.findall(text):
        clean = doi.rstrip(".,;:)")
        url = f"https://doi.org/{clean}"
        if url not in seen:
            seen.add(url); out.append(CitationLead(url, "doi", clean))
    for aid in ARXIV_RE.findall(text):
        url = f"https://arxiv.org/abs/{aid}"
        if url not in seen:
            seen.add(url); out.append(CitationLead(url, "arxiv", aid))
    for raw in URL_RE.findall(text):
        url = canonicalize_url(raw.rstrip(".,;:)") )
        host = (urlsplit(url).hostname or "").casefold()
        if url.startswith(("http://", "https://")) and url not in seen and host:
            seen.add(url); out.append(CitationLead(url, "url", host))
        if len(out) >= limit: break
    return out[:limit]
