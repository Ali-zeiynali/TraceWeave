from __future__ import annotations

import time

from traceweave.config import Settings
from traceweave.models import SearchResult
from traceweave.search.base import SearchBackend, SearchError
from traceweave.search.ddgs_backend import DDGSSearch
from traceweave.search.public_indexes import PublicIndexSearch
from traceweave.search.searxng import SearXNGSearch


class AutoSearch:
    name = "auto"

    def __init__(self, primary: SearchBackend, fallback: SearchBackend, *more: SearchBackend):
        self.backends = (primary, fallback, *more)
        self.last_backend = ""
        self._failures: dict[str, int] = {}
        self._retry_until: dict[str, float] = {}

    async def search(self, query: str, *, limit: int, language: str) -> list[SearchResult]:
        errors: list[str] = []
        for backend in self.backends:
            if self._retry_until.get(backend.name, 0) > time.monotonic():
                continue
            try:
                results = await backend.search(query, limit=limit, language=language)
                if results:
                    self.last_backend = backend.name
                    self._failures.pop(backend.name, None)
                    self._retry_until.pop(backend.name, None)
                    return results
            except SearchError as exc:
                errors.append(f"{backend.name}: {exc}")
                failures = self._failures.get(backend.name, 0) + 1
                self._failures[backend.name] = failures
                self._retry_until[backend.name] = time.monotonic() + min(
                    1800, 300 * (2 ** min(failures - 1, 3))
                )
        raise SearchError("All search backends failed: " + " | ".join(errors[-3:]))


def build_search(settings: Settings) -> SearchBackend:
    searx = SearXNGSearch(settings.searxng_url, settings.search_timeout_seconds)
    ddgs = DDGSSearch(settings.search_timeout_seconds)
    public_indexes = PublicIndexSearch(settings.search_timeout_seconds, settings.user_agent)
    if settings.search_backend == "searxng":
        return searx
    if settings.search_backend == "ddgs":
        return ddgs
    return AutoSearch(searx, ddgs, public_indexes)
