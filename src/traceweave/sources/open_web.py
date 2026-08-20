from __future__ import annotations

import asyncio
from urllib.parse import quote

import httpx

from traceweave.models import SearchResult


class OpenWebSources:
    """No-key, public discovery APIs that add news, encyclopedia and community coverage."""

    def __init__(self, *, timeout: float = 20.0, user_agent: str = "TraceWeave/0.5"):
        self.timeout = timeout
        self.headers = {"User-Agent": user_agent, "Accept": "application/json"}

    async def search(self, query: str, limit: int = 5) -> tuple[list[SearchResult], list[str]]:
        jobs = (self._gdelt(query, limit), self._wikipedia(query, limit), self._hacker_news(query, limit))
        batches = await asyncio.gather(*jobs, return_exceptions=True)
        rows: list[SearchResult] = []
        errors: list[str] = []
        seen: set[str] = set()
        for name, batch in zip(("gdelt", "wikipedia", "hackernews"), batches, strict=True):
            if isinstance(batch, BaseException):
                errors.append(f"{name}:{type(batch).__name__}:{batch}"[:500])
                continue
            for row in batch:
                if row.url and row.url not in seen:
                    rows.append(row)
                    seen.add(row.url)
        return rows, errors

    async def _json(self, url: str, params: dict[str, str]) -> object:
        async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers, trust_env=False) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    async def _gdelt(self, query: str, limit: int) -> list[SearchResult]:
        payload = await self._json(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            {"query": query, "mode": "artlist", "maxrecords": str(min(25, limit)), "format": "json"},
        )
        articles = payload.get("articles", []) if isinstance(payload, dict) else []
        return [
            SearchResult(
                url=str(item.get("url") or ""),
                title=str(item.get("title") or ""),
                snippet=f"{item.get('domain', '')} · {item.get('language', '')}",
                engine="gdelt",
                category="news-index",
                published_at=str(item.get("seendate") or "") or None,
                raw=item,
            )
            for item in articles[:limit]
            if item.get("url")
        ]

    async def _wikipedia(self, query: str, limit: int) -> list[SearchResult]:
        payload = await self._json(
            "https://en.wikipedia.org/w/api.php",
            {
                "action": "query",
                "generator": "search",
                "gsrsearch": query,
                "gsrlimit": str(min(20, limit)),
                "prop": "extracts|info",
                "exintro": "1",
                "explaintext": "1",
                "inprop": "url",
                "format": "json",
            },
        )
        pages = ((payload.get("query") or {}).get("pages") or {}) if isinstance(payload, dict) else {}
        return [
            SearchResult(
                url=str(item.get("fullurl") or f"https://en.wikipedia.org/?curid={item.get('pageid')}"),
                title=str(item.get("title") or ""),
                snippet=str(item.get("extract") or "")[:1000],
                engine="mediawiki",
                category="reference",
                raw=item,
            )
            for item in list(pages.values())[:limit]
        ]

    async def _hacker_news(self, query: str, limit: int) -> list[SearchResult]:
        payload = await self._json(
            "https://hn.algolia.com/api/v1/search",
            {
                "query": query,
                "hitsPerPage": str(min(20, limit)),
                "restrictSearchableAttributes": "title,story_text",
            },
        )
        hits = payload.get("hits", []) if isinstance(payload, dict) else []
        rows = []
        for item in hits[:limit]:
            object_id = str(item.get("objectID") or "")
            url = str(item.get("url") or f"https://news.ycombinator.com/item?id={quote(object_id)}")
            rows.append(
                SearchResult(
                    url=url,
                    title=str(item.get("title") or item.get("story_title") or ""),
                    snippet=str(item.get("story_text") or "")[:1000],
                    engine="hackernews-algolia",
                    category="community-index",
                    published_at=str(item.get("created_at") or "") or None,
                    raw=item,
                )
            )
        return rows
