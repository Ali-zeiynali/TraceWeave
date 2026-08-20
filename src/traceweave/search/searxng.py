from __future__ import annotations

import httpx

from traceweave.models import SearchResult
from traceweave.search.base import SearchError


class SearXNGSearch:
    name = "searxng"

    def __init__(self, base_url: str, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def search(self, query: str, *, limit: int, language: str) -> list[SearchResult]:
        params = {
            "q": query,
            "format": "json",
            "categories": "general,news",
            "safesearch": 1,
        }
        if language and language != "all":
            params["language"] = language
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/search", params=params)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchError(f"SearXNG failed: {exc}") from exc

        results: list[SearchResult] = []
        for item in payload.get("results", [])[:limit]:
            url = item.get("url")
            if not url:
                continue
            results.append(
                SearchResult(
                    url=url,
                    title=item.get("title") or "",
                    snippet=item.get("content") or "",
                    engine=", ".join(item.get("engines") or [item.get("engine", "searxng")]),
                    category=item.get("category") or "web",
                    published_at=str(item.get("publishedDate")) if item.get("publishedDate") else None,
                    raw={k: v for k, v in item.items() if k not in {"img_src"}},
                )
            )
        return results
