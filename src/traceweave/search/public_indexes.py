from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit

from traceweave.fetcher import FetchError, SafeFetcher
from traceweave.models import SearchResult
from traceweave.search.base import SearchError
from traceweave.sources.open_web import OpenWebSources


class PublicIndexSearch:
    """No-key fallback when consumer search frontends are unavailable."""

    name = "public-indexes"

    def __init__(self, timeout: float, user_agent: str):
        self.source = OpenWebSources(timeout=timeout, user_agent=user_agent)
        self.fetcher = SafeFetcher(timeout=timeout, max_bytes=5_000_000, user_agent=user_agent, retries=1)

    async def search(self, query: str, *, limit: int, language: str) -> list[SearchResult]:
        del language
        site_rows = await self._site_map(query, limit)
        if site_rows:
            return site_rows
        rows, errors = await self.source.search(query, limit)
        if not rows:
            raise SearchError("Public indexes returned no results: " + " | ".join(errors[-3:]))
        return rows[:limit]

    async def _site_map(self, query: str, limit: int) -> list[SearchResult]:
        match = re.search(r"\bsite:([a-z0-9.-]+)(?:/[^\s]+)?", query, flags=re.IGNORECASE)
        if not match:
            return []
        host = match.group(1).casefold().strip(".")
        origin = f"https://{host}/"
        maps = [urljoin(origin, "sitemap.xml")]
        try:
            robots = await self.fetcher.fetch(urljoin(origin, "robots.txt"), accept="text/plain,*/*;q=0.1")
            maps.extend(
                line.split(":", 1)[1].strip()
                for line in robots.text.splitlines()
                if line.casefold().startswith("sitemap:")
            )
        except FetchError:
            pass
        urls: list[str] = []
        child_maps: list[str] = []
        for sitemap in list(dict.fromkeys(maps))[:4]:
            try:
                result = await self.fetcher.fetch(sitemap, accept="application/xml,text/xml,*/*;q=0.1")
                found, children = _locs(result.raw)
                urls.extend(found)
                child_maps.extend(children)
            except FetchError:
                continue
        for sitemap in child_maps[:6]:
            try:
                result = await self.fetcher.fetch(sitemap, accept="application/xml,text/xml,*/*;q=0.1")
                found, _ = _locs(result.raw)
                urls.extend(found)
            except FetchError:
                continue
        terms = {
            token.casefold()
            for token in re.findall(r"[\w-]{3,}", query)
            if token.casefold() not in {"site", "filetype", "after", "before", "and", "the", "or"}
        }
        ranked = sorted(
            dict.fromkeys(urls),
            key=lambda url: (-sum(term in url.casefold() for term in terms), len(url)),
        )
        rows = [url for url in ranked if not terms or any(term in url.casefold() for term in terms)][:limit]
        return [
            SearchResult(
                url=url,
                title=(urlsplit(url).path.rsplit("/", 1)[-1] or host).replace("-", " "),
                snippet=f"Public sitemap match on {host}; content is fetched separately under robots policy.",
                engine="sitemap-index",
                category="official-site-index",
                raw={"site": host, "query": query},
            )
            for url in rows
        ]


def _locs(raw: bytes) -> tuple[list[str], list[str]]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return [], []
    locs = [node.text.strip() for node in root.iter() if node.tag.casefold().endswith("loc") and node.text]
    return ([], locs[:100]) if root.tag.casefold().endswith("sitemapindex") else (locs[:5000], [])
