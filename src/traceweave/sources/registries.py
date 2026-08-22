from __future__ import annotations

import asyncio
import base64
import ipaddress
import os
import re
from typing import Any
from urllib.parse import quote

import httpx

from traceweave.models import SearchResult

_DOMAIN_RE = re.compile(r"(?<![@\w.-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?![\w.-])", re.I)


class RegistrySources:
    """Passive, no-auth registry discovery with bounded requests and normalized results."""

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        user_agent: str = "TraceWeave/1.0.2",
        certificate_transparency_enabled: bool = True,
        urlscan_enabled: bool = True,
        sec_edgar_enabled: bool = True,
        peeringdb_enabled: bool = True,
        companies_house_enabled: bool = True,
    ):
        self.timeout = timeout
        self.headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self.certificate_transparency_enabled = certificate_transparency_enabled
        self.urlscan_enabled = urlscan_enabled
        self.sec_edgar_enabled = sec_edgar_enabled
        self.peeringdb_enabled = peeringdb_enabled
        self.companies_house_enabled = companies_house_enabled
        self._sec_companies: list[dict[str, Any]] | None = None

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        jobs = [self._gleif(query, limit), self._ror(query, limit), self._orcid(query, limit)]
        if self.peeringdb_enabled:
            jobs.append(self._peeringdb(query, limit))
        if self.sec_edgar_enabled and os.getenv("SEC_USER_AGENT", "").strip():
            jobs.append(self._sec_edgar(query, limit))
        if self.companies_house_enabled and os.getenv("COMPANIES_HOUSE_API_KEY", "").strip():
            jobs.append(self._companies_house(query, limit))
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
            if self.certificate_transparency_enabled:
                jobs.append(self._certificate_transparency(domain.casefold(), 20))
            if self.urlscan_enabled and os.getenv("URLSCAN_API_KEY", "").strip():
                jobs.append(self._urlscan(domain.casefold(), 10))
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
        record_types = ("A", "AAAA", "CNAME", "MX", "NS", "TXT", "CAA", "SOA")

        async def resolve(record_type: str) -> tuple[str, dict[str, Any]]:
            payload = await self._get(
                "https://cloudflare-dns.com/dns-query",
                params={"name": domain, "type": record_type},
                headers={"Accept": "application/dns-json"},
            )
            return record_type, payload

        batches = await asyncio.gather(*(resolve(kind) for kind in record_types), return_exceptions=True)
        rows: list[SearchResult] = []
        for batch in batches:
            if isinstance(batch, BaseException):
                continue
            record_type, payload = batch
            answers = payload.get("Answer") or []
            if not answers:
                continue
            snippet = ", ".join(str(item.get("data", "")) for item in answers[:12])
            rows.append(
                SearchResult(
                    url=(f"https://cloudflare-dns.com/dns-query?name={quote(domain)}&type={record_type}"),
                    title=f"DNS {record_type}: {domain}",
                    snippet=snippet,
                    engine="dns-over-https",
                    category="network-registry",
                    raw=payload,
                )
            )
        return rows

    async def _certificate_transparency(self, domain: str, limit: int) -> list[SearchResult]:
        async with httpx.AsyncClient(
            timeout=self.timeout, follow_redirects=True, headers=self.headers
        ) as client:
            response = await client.get("https://crt.sh/", params={"q": f"%.{domain}", "output": "json"})
            response.raise_for_status()
            payload = response.json()
        names: list[str] = []
        seen: set[str] = set()
        for item in payload if isinstance(payload, list) else []:
            for value in str(item.get("name_value") or "").splitlines():
                name = value.strip().casefold().removeprefix("*.")
                if name == domain or not name.endswith(f".{domain}") or name in seen:
                    continue
                seen.add(name)
                names.append(name)
                if len(names) >= limit:
                    break
            if len(names) >= limit:
                break
        if not names:
            return []
        return [
            SearchResult(
                url=f"https://crt.sh/?q=%25.{quote(domain)}",
                title=f"Certificate Transparency names: {domain}",
                snippet=", ".join(names),
                engine="crtsh",
                category="certificate-transparency",
                raw={"domain": domain, "names": names, "passive": True},
            )
        ]

    async def _urlscan(self, domain: str, limit: int) -> list[SearchResult]:
        key = os.getenv("URLSCAN_API_KEY", "").strip()
        if not key:
            return []
        payload = await self._get(
            "https://urlscan.io/api/v1/search/",
            params={"q": f"page.domain:{domain}", "size": str(min(100, max(1, limit)))},
            headers={"api-key": key},
        )
        rows: list[SearchResult] = []
        for item in payload.get("results", [])[:limit]:
            page = item.get("page") or {}
            task = item.get("task") or {}
            scan_id = str(item.get("_id") or item.get("uuid") or "")
            page_url = str(page.get("url") or task.get("url") or "")
            if not scan_id or not page_url:
                continue
            rows.append(
                SearchResult(
                    url=f"https://urlscan.io/result/{scan_id}/",
                    title=f"urlscan snapshot: {page.get('domain') or domain}",
                    snippet=f"{page_url} · {task.get('time') or ''}",
                    engine="urlscan-search",
                    category="web-intel",
                    published_at=str(task.get("time") or "") or None,
                    raw=item,
                )
            )
        return rows

    async def _peeringdb(self, query: str, limit: int) -> list[SearchResult]:
        # PeeringDB accepts ``name__contains``. Unknown Django-style filters are silently
        # ignored by the API, so using ``icontains`` can look successful while returning
        # unrelated first-page organizations. Keep the candidate set bounded and explicit.
        without_domains = _DOMAIN_RE.sub(" ", query)
        phrase = " ".join(without_domains.split())[:120]
        tokens = sorted(
            {token for token in re.findall(r"[\w&.-]{3,}", phrase, re.UNICODE) if not token.isdigit()},
            key=lambda value: (-len(value), value.casefold()),
        )
        candidates = []
        for candidate in (phrase, *tokens):
            if candidate and candidate.casefold() not in {value.casefold() for value in candidates}:
                candidates.append(candidate)
        payloads = await asyncio.gather(
            *(
                self._get(
                    "https://www.peeringdb.com/api/org",
                    params={"name__contains": candidate, "limit": str(min(20, max(1, limit)))},
                )
                for candidate in candidates[:3]
            ),
            return_exceptions=True,
        )
        rows: list[SearchResult] = []
        seen: set[int] = set()
        for payload in payloads:
            if isinstance(payload, BaseException):
                continue
            for item in payload.get("data", []):
                org_id = int(item.get("id") or 0)
                if not org_id or org_id in seen:
                    continue
                seen.add(org_id)
                rows.append(
                    SearchResult(
                        url=f"https://www.peeringdb.com/org/{org_id}",
                        title=f"PeeringDB: {item.get('name') or org_id}",
                        snippet=str(item.get("website") or item.get("notes") or "")[:1000],
                        engine="peeringdb",
                        category="network-registry",
                        raw=item,
                    )
                )
                if len(rows) >= limit:
                    return rows
        return rows

    async def _companies_house(self, query: str, limit: int) -> list[SearchResult]:
        key = os.getenv("COMPANIES_HOUSE_API_KEY", "").strip()
        if not key:
            return []
        auth = base64.b64encode(f"{key}:".encode()).decode()
        payload = await self._get(
            "https://api.company-information.service.gov.uk/search/companies",
            params={"q": query[:200], "items_per_page": str(min(20, max(1, limit)))},
            headers={"Authorization": f"Basic {auth}"},
        )
        rows: list[SearchResult] = []
        for item in payload.get("items", [])[:limit]:
            number = str(item.get("company_number") or "")
            if not number:
                continue
            rows.append(
                SearchResult(
                    url=f"https://find-and-update.company-information.service.gov.uk/company/{number}",
                    title=f"{item.get('title') or number} — {number}",
                    snippet=f"{item.get('company_status') or ''} · {item.get('date_of_creation') or ''}",
                    engine="companies-house",
                    category="registry",
                    published_at=str(item.get("date_of_creation") or "") or None,
                    raw=item,
                )
            )
        return rows

    async def _sec_edgar(self, query: str, limit: int) -> list[SearchResult]:
        user_agent = os.getenv("SEC_USER_AGENT", "").strip()
        if not user_agent:
            return []
        headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
        if self._sec_companies is None:
            payload = await self._get("https://www.sec.gov/files/company_tickers.json", headers=headers)
            self._sec_companies = [item for item in payload.values() if isinstance(item, dict)]
        terms = [term.casefold() for term in re.findall(r"[\w.-]{2,}", query)]
        ranked = []
        for item in self._sec_companies or []:
            haystack = f"{item.get('title', '')} {item.get('ticker', '')}".casefold()
            score = sum(term in haystack for term in terms)
            if score:
                ranked.append((score, item))
        ranked.sort(key=lambda row: (-row[0], str(row[1].get("title") or "")))
        rows: list[SearchResult] = []
        for _, item in ranked[:limit]:
            cik = str(item.get("cik_str") or "").zfill(10)
            if not cik:
                continue
            rows.append(
                SearchResult(
                    url=f"https://data.sec.gov/submissions/CIK{cik}.json",
                    title=f"SEC EDGAR: {item.get('title') or cik} ({item.get('ticker') or ''})",
                    snippet="Public filer submissions index; fetch the cited filing before treating it as evidence.",
                    engine="sec-edgar",
                    category="filing-registry",
                    raw={"cik": cik, "ticker": item.get("ticker"), "name": item.get("title")},
                )
            )
        return rows

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
