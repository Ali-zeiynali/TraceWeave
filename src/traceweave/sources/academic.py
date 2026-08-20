from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import httpx

from traceweave.sources.common import SpecialistResult


class AcademicSources:
    def __init__(self, *, timeout: float = 20, mailto: str = ""):
        self.timeout = timeout
        self.mailto = mailto

    async def search(self, query: str, limit: int = 5) -> list[SpecialistResult]:
        groups = await _gather(
            self._openalex(query, limit), self._crossref(query, limit), self._arxiv(query, limit)
        )
        out: list[SpecialistResult] = []
        seen: set[str] = set()
        for rows in groups:
            for row in rows:
                if row.url and row.url not in seen:
                    seen.add(row.url)
                    out.append(row)
        return out[: limit * 3]

    async def _openalex(self, query: str, limit: int) -> list[SpecialistResult]:
        params = {"search": query, "per-page": str(limit)}
        if self.mailto:
            params["mailto"] = self.mailto
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            r = await client.get("https://api.openalex.org/works", params=params)
            r.raise_for_status()
            body = r.json()
        out = []
        for item in body.get("results", [])[:limit]:
            doi = str(item.get("doi") or "")
            primary = item.get("primary_location") or {}
            landing = str(primary.get("landing_page_url") or "") if isinstance(primary, dict) else ""
            url = doi or landing or str(item.get("id") or "")
            authors = []
            for authorship in (item.get("authorships") or [])[:8]:
                author = authorship.get("author") or {}
                if author.get("display_name"):
                    authors.append(str(author["display_name"]))
            out.append(
                SpecialistResult(
                    url=url,
                    title=str(item.get("display_name") or item.get("title") or ""),
                    snippet=("Authors: " + ", ".join(authors)) if authors else "",
                    engine="openalex",
                    category="academic",
                    published_at=str(item.get("publication_date") or "") or None,
                    raw={
                        "openalex_id": item.get("id"),
                        "doi": doi,
                        "cited_by_count": item.get("cited_by_count"),
                        "type": item.get("type"),
                    },
                )
            )
        return out

    async def _crossref(self, query: str, limit: int) -> list[SpecialistResult]:
        headers = {"User-Agent": f"TraceWeave/0.5{'; mailto:' + self.mailto if self.mailto else ''}"}
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False, headers=headers) as client:
            r = await client.get(
                "https://api.crossref.org/works",
                params={
                    "query.bibliographic": query,
                    "rows": str(limit),
                    "select": "DOI,title,URL,author,published-print,published-online,type,publisher",
                },
            )
            r.raise_for_status()
            body = r.json()
        out = []
        for item in body.get("message", {}).get("items", [])[:limit]:
            doi = str(item.get("DOI") or "")
            url = f"https://doi.org/{doi}" if doi else str(item.get("URL") or "")
            title = " ".join(item.get("title") or [])
            authors = [
                " ".join(str(a.get(k) or "") for k in ("given", "family")).strip()
                for a in (item.get("author") or [])[:8]
            ]
            date_parts = (
                (item.get("published-online") or item.get("published-print") or {}).get("date-parts") or [[]]
            )[0]
            published = "-".join(str(x) for x in date_parts) if date_parts else None
            out.append(
                SpecialistResult(
                    url=url,
                    title=title,
                    snippet="Authors: " + ", ".join(x for x in authors if x),
                    engine="crossref",
                    category="academic",
                    published_at=published,
                    raw={"doi": doi, "publisher": item.get("publisher"), "type": item.get("type")},
                )
            )
        return out

    async def _arxiv(self, query: str, limit: int) -> list[SpecialistResult]:
        url = f"https://export.arxiv.org/api/query?search_query=all:{quote_plus(query)}&start=0&max_results={limit}&sortBy=relevance"
        async with httpx.AsyncClient(
            timeout=self.timeout, trust_env=False, headers={"User-Agent": "TraceWeave/0.5"}
        ) as client:
            r = await client.get(url)
            r.raise_for_status()
        root = ET.fromstring(r.text)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        out = []
        for entry in root.findall("a:entry", ns)[:limit]:
            link = (entry.findtext("a:id", default="", namespaces=ns) or "").strip()
            title = " ".join((entry.findtext("a:title", default="", namespaces=ns) or "").split())
            summary = " ".join((entry.findtext("a:summary", default="", namespaces=ns) or "").split())[:1200]
            published = entry.findtext("a:published", default="", namespaces=ns) or None
            out.append(
                SpecialistResult(
                    url=link,
                    title=title,
                    snippet=summary,
                    engine="arxiv",
                    category="academic",
                    published_at=published,
                    raw={"arxiv_id": link.rsplit("/", 1)[-1]},
                )
            )
        return out


async def _gather(*coros):
    import asyncio

    rows = await asyncio.gather(*coros, return_exceptions=True)
    return [x if isinstance(x, list) else [] for x in rows]
