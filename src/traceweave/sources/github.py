from __future__ import annotations

import httpx

from traceweave.sources.common import SpecialistResult


class GitHubSource:
    def __init__(self, *, token: str = "", timeout: float = 20):
        self.token = token
        self.timeout = timeout

    async def search(self, query: str, limit: int = 5) -> list[SpecialistResult]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "TraceWeave/0.5"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        out: list[SpecialistResult] = []
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False, headers=headers) as client:
            repo = await client.get("https://api.github.com/search/repositories", params={"q": query, "per_page": min(limit, 10), "sort": "updated"})
            if repo.status_code < 400:
                for item in repo.json().get("items", [])[:limit]:
                    out.append(SpecialistResult(
                        url=str(item.get("html_url") or ""), title=str(item.get("full_name") or ""),
                        snippet=str(item.get("description") or ""), engine="github-repositories", category="code",
                        published_at=str(item.get("updated_at") or "") or None,
                        raw={"stars": item.get("stargazers_count"), "language": item.get("language"), "owner": (item.get("owner") or {}).get("login")},
                    ))
            issues = await client.get("https://api.github.com/search/issues", params={"q": query, "per_page": min(limit, 10), "sort": "updated"})
            if issues.status_code < 400:
                for item in issues.json().get("items", [])[:limit]:
                    out.append(SpecialistResult(
                        url=str(item.get("html_url") or ""), title=str(item.get("title") or ""),
                        snippet=str(item.get("body") or "")[:1200], engine="github-issues", category="code",
                        published_at=str(item.get("updated_at") or "") or None,
                        raw={"state": item.get("state"), "comments": item.get("comments"), "user": (item.get("user") or {}).get("login")},
                    ))
        return out
