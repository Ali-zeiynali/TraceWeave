from __future__ import annotations

import asyncio

from traceweave.models import SearchResult
from traceweave.search.base import SearchError


class DDGSSearch:
    name = "ddgs"

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    def _sync_search(self, query: str, limit: int) -> list[SearchResult]:
        try:
            from ddgs import DDGS
        except ImportError as exc:
            raise SearchError("DDGS is not installed. Run: pip install ddgs") from exc

        ddgs = DDGS(timeout=int(max(5, self.timeout)))
        out: list[SearchResult] = []
        errors: list[str] = []

        try:
            for item in ddgs.text(query, max_results=limit):
                url = item.get("href") or item.get("url")
                if not url:
                    continue
                out.append(
                    SearchResult(
                        url=url,
                        title=item.get("title") or "",
                        snippet=item.get("body") or item.get("description") or "",
                        engine=item.get("source") or "ddgs",
                        category="web",
                        raw=dict(item),
                    )
                )
        except Exception as exc:
            errors.append(f"text: {exc}")

        # News is an enrichment pass. Its failure must not discard successful web results.
        try:
            news_limit = min(4, max(1, limit // 3))
            for item in ddgs.news(query, max_results=news_limit):
                url = item.get("url") or item.get("href")
                if not url:
                    continue
                out.append(
                    SearchResult(
                        url=url,
                        title=item.get("title") or "",
                        snippet=item.get("body") or item.get("excerpt") or "",
                        engine=item.get("source") or "ddgs-news",
                        category="news",
                        published_at=item.get("date"),
                        raw=dict(item),
                    )
                )
        except Exception as exc:
            errors.append(f"news: {exc}")

        dedup: dict[tuple[str, str, str], SearchResult] = {}
        for item in out:
            dedup.setdefault((item.url, item.category, item.engine), item)
        results = list(dedup.values())[:limit]
        if not results and errors:
            raise SearchError("DDGS failed: " + " | ".join(errors))
        return results

    async def search(self, query: str, *, limit: int, language: str) -> list[SearchResult]:
        del language  # language/region-specific routing arrives in a later stage
        return await asyncio.to_thread(self._sync_search, query, limit)
