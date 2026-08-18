from __future__ import annotations

from typing import Protocol

from traceweave.models import SearchResult


class SearchError(RuntimeError):
    pass


class SearchBackend(Protocol):
    name: str

    async def search(self, query: str, *, limit: int, language: str) -> list[SearchResult]: ...
