from __future__ import annotations

from traceweave.config import Settings
from traceweave.models import SearchResult
from traceweave.search.base import SearchBackend, SearchError
from traceweave.search.ddgs_backend import DDGSSearch
from traceweave.search.searxng import SearXNGSearch


class AutoSearch:
    name = "auto"

    def __init__(self, primary: SearchBackend, fallback: SearchBackend):
        self.primary = primary
        self.fallback = fallback
        self.last_backend = ""

    async def search(self, query: str, *, limit: int, language: str) -> list[SearchResult]:
        try:
            results = await self.primary.search(query, limit=limit, language=language)
            if results:
                self.last_backend = self.primary.name
                return results
        except SearchError:
            pass
        results = await self.fallback.search(query, limit=limit, language=language)
        self.last_backend = self.fallback.name
        return results


def build_search(settings: Settings) -> SearchBackend:
    searx = SearXNGSearch(settings.searxng_url, settings.search_timeout_seconds)
    ddgs = DDGSSearch(settings.search_timeout_seconds)
    if settings.search_backend == "searxng":
        return searx
    if settings.search_backend == "ddgs":
        return ddgs
    return AutoSearch(searx, ddgs)
