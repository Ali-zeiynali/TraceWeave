from __future__ import annotations

import asyncio
import ipaddress
import re
from typing import Any
from urllib.parse import quote

import httpx

from traceweave.models import SearchResult

_DOMAIN_RE = re.compile(r"(?<![@\w.-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?![\w.-])", re.I)


class RegistrySources:
    """Passive, no-auth registry discovery with bounded requests and normalized results."""

    def __init__(self, *, timeout: float = 20.0, user_agent: str = "TraceWeave/0.5"):
        self.timeout = timeout
        self.headers = {"User-Agent": user_agent, "Accept": "application/json"}

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        jobs = [self._gleif(query, limit), self._ror(query, limit), self._orcid(query, limit)]
        jobs.extend(self._network_jobs(query))
        batches = await asyncio.gather(*jobs, return_exceptions=True)
        rows: list[SearchResult] = []
        seen: set[str] = set()
        for batch in batches:
            if isinstance(batch, BaseException):
                continue
            for row in batch:
                if row.url not in seen:
                    rows.append(row)
                    seen.add(row.url)
        return rows[: max(limit * 3, limit)]

    def _network_jobs(self, query: str) -> list[Any]:
        jobs: list[Any] = []
        for domain in _DOMAIN_RE.findall(query)[:2]:
            jobs.append(self._rdap_domain(domain.casefold()))
            jobs.append(self._dns(domain.casefold()))
        for token in query.split():
            try:
                ipaddress.ip_address(token.strip("[](),"))
            except ValueError:
                continue
            jobs.append(self._ripestat(token.strip("[](),")))
            break
        return jobs

    async def _get(
        self, url: str, *, params: dict[str, str] | None = None, headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        merged = dict(self.headers)
        merged.update(headers or {})
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=merged) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        return payload if isinstance(payload, dict) else {}

    async def _gleif(self, query: str, limit: int) -> list[SearchResult]:
        payload = await self._get(
            "https://api.gleif.org/api/v1/lei-records",
            params={"filter[fulltext]": query, "page[size]": str(min(10, limit))},
        )
        rows = []
        for item in payload.get("data", [])[:limit]:
            attrs = item.get("attributes", {})
            entity = attrs.get("entity", {})
            name = (entity.get("legalName") or {}).get("name") or item.get("id", "")
            lei = str(item.get("id", ""))
            url = str(
                (item.get("links") or {}).get("self") or f"https://api.gleif.org/api/v1/lei-records/{lei}"
            )
            rows.append(
                SearchResult(
                    url=url,
                    title=f"{name} — LEI {lei}",
                    snippet=str(entity.get("status", "")),
                    engine="gleif",
                    category="registry",
                    raw=item,
                )
            )
        return rows

    async def _ror(self, query: str, limit: int) -> list[SearchResult]:
        payload = await self._get(
            "https://api.ror.org/v2/organizations", params={"query": query, "page": "1"}
        )
        rows = []
        for item in payload.get("items", [])[:limit]:
            names = item.get("names") or []
            name = next((x.get("value") for x in names if "ror_display" in (x.get("types") or [])), None)
            name = name or next((x.get("value") for x in names if x.get("value")), "")
            rows.append(
                SearchResult(
                    url=str(item.get("id", "")),
                    title=str(name),
                    snippet=", ".join(item.get("types") or []),
                    engine="ror",
                    category="registry",
                    raw=item,
                )
            )
        return rows

    async def _orcid(self, query: str, limit: int) -> list[SearchResult]:
        payload = await self._get(
            "https://pub.orcid.org/v3.0/expanded-search/",
            params={"q": query, "rows": str(min(10, limit))},
            headers={"Accept": "application/vnd.orcid+json"},
        )
        rows = []
        for item in payload.get("expanded-result", [])[:limit]:
            oid = str(item.get("orcid-id", ""))
            name = " ".join(x for x in (item.get("given-names"), item.get("family-names")) if x)
            rows.append(
                SearchResult(
                    url=f"https://orcid.org/{oid}",
                    title=name or oid,
                    snippet="ORCID candidate — verify with affiliation/work evidence before merging",
                    engine="orcid",
                    category="person-registry",
                    raw=item,
                )
            )
        return rows

    async def _rdap_domain(self, domain: str) -> list[SearchResult]:
        payload = await self._get(f"https://rdap.org/domain/{quote(domain, safe='')}")
        return [
            SearchResult(
                url=f"https://rdap.org/domain/{domain}",
                title=f"RDAP: {domain}",
                snippet=str(payload.get("status") or ""),
                engine="rdap",
                category="network-registry",
                raw=payload,
            )
        ]

    async def _dns(self, domain: str) -> list[SearchResult]:
        payload = await self._get(
            "https://cloudflare-dns.com/dns-query",
            params={"name": domain, "type": "A"},
            headers={"Accept": "application/dns-json"},
        )
        answers = payload.get("Answer") or []
        snippet = ", ".join(str(item.get("data", "")) for item in answers[:8])
        return [
            SearchResult(
                url=f"https://cloudflare-dns.com/dns-query?name={quote(domain)}&type=A",
                title=f"DNS A: {domain}",
                snippet=snippet,
                engine="dns-over-https",
                category="network-registry",
                raw=payload,
            )
        ]

    async def _ripestat(self, resource: str) -> list[SearchResult]:
        payload = await self._get(
            "https://stat.ripe.net/data/prefix-overview/data.json", params={"resource": resource}
        )
        data = payload.get("data") or {}
        return [
            SearchResult(
                url=f"https://stat.ripe.net/{quote(resource, safe=':/')}",
                title=f"RIPEstat: {resource}",
                snippet=f"ASN {data.get('asns', [])} {data.get('holder', '')}",
                engine="ripestat",
                category="network-registry",
                raw=payload,
            )
        ]
