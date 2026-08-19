from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from traceweave.fetcher import FetchError, PageLink, SafeFetcher
from traceweave.models import ResearchSpec
from traceweave.storage import Storage
from traceweave.utils import canonicalize_url, lexical_overlap


@dataclass(slots=True)
class FrontierDecision:
    url: str
    anchor: str
    relation: str
    depth: int
    score: float


class FrontierManager:
    def __init__(self, storage: Storage, fetcher: SafeFetcher, *, user_agent: str, respect_robots: bool = True):
        self.storage = storage
        self.fetcher = fetcher
        self.user_agent = user_agent
        self.respect_robots = respect_robots
        self._robots: dict[str, RobotFileParser | None] = {}

    def score_link(self, spec: ResearchSpec, parent_url: str, link: PageLink, depth: int) -> float:
        parent_host = (urlsplit(parent_url).hostname or "").casefold()
        target = canonicalize_url(link.url)
        target_host = (urlsplit(target).hostname or "").casefold()
        signal = f"{link.anchor} {target}"
        overlap = lexical_overlap(f"{spec.topic} {spec.angle}", signal)
        score = 0.08 + min(0.55, overlap * 1.8)
        if target_host == parent_host:
            score += 0.12
        if link.relation == "citation":
            score += 0.16
        low = target.casefold()
        if any(x in low for x in (".pdf", "/report", "/research", "/press", "/news", "/blog", "/docs", "/publication", "/investor")):
            score += 0.12
        if any(x in low for x in ("/login", "/signup", "/privacy", "/terms", "/cart", "/account")):
            score -= 0.35
        score -= max(0, depth - 1) * 0.035
        return max(0.0, min(1.0, score))

    def add_page_links(self, run_id: str, spec: ResearchSpec, *, source_id: int, parent_url: str,
                       links: list[PageLink], depth: int) -> int:
        if depth > spec.resolved_depth():
            return 0
        added = 0
        for link in links:
            score = self.score_link(spec, parent_url, link, depth)
            if score < 0.03:
                continue
            if self.storage.add_frontier(
                run_id, link.url, parent_source_id=source_id, anchor=link.anchor,
                relation=link.relation, depth=depth, score=score,
            ):
                added += 1
        return added

    async def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            robots_url = urljoin(origin + "/", "robots.txt")
            parser = RobotFileParser()
            parser.set_url(robots_url)
            try:
                result = await self.fetcher.fetch(robots_url, accept="text/plain,*/*;q=0.1")
                parser.parse(result.text.splitlines())
                self._robots[origin] = parser
            except FetchError:
                self._robots[origin] = None
        parser = self._robots[origin]
        return True if parser is None else bool(parser.can_fetch(self.user_agent, url))

    async def discover_domain(self, run_id: str, spec: ResearchSpec, source_id: int, page_url: str) -> int:
        """Discover public sitemap/feed URLs once per run/domain, bounded for stability."""
        parts = urlsplit(page_url)
        domain = (parts.hostname or "").casefold()
        if not domain or self.storage.domain_checked(run_id, domain, "sitemap_checked"):
            return 0
        self.storage.mark_domain_checked(run_id, domain, "sitemap_checked")
        origin = f"{parts.scheme}://{parts.netloc}"
        sitemap_urls = {urljoin(origin + "/", "sitemap.xml")}
        try:
            robots = await self.fetcher.fetch(urljoin(origin + "/", "robots.txt"), accept="text/plain,*/*;q=0.1")
            for line in robots.text.splitlines():
                if line.casefold().startswith("sitemap:"):
                    sitemap_urls.add(line.split(":", 1)[1].strip())
        except FetchError:
            pass

        discovered: list[str] = []
        nested: list[str] = []
        for sitemap_url in list(sitemap_urls)[:4]:
            try:
                result = await self.fetcher.fetch(sitemap_url, accept="application/xml,text/xml,*/*;q=0.1")
            except FetchError:
                continue
            urls, child_maps = _parse_sitemap(result.raw)
            discovered.extend(urls[:1000])
            nested.extend(child_maps[:4])
        for sitemap_url in nested[:4]:
            try:
                result = await self.fetcher.fetch(sitemap_url, accept="application/xml,text/xml,*/*;q=0.1")
            except FetchError:
                continue
            urls, _ = _parse_sitemap(result.raw)
            discovered.extend(urls[:1000])

        added = 0
        for url in discovered[:2000]:
            link = PageLink(url=url, anchor="sitemap", relation="sitemap")
            score = self.score_link(spec, page_url, link, depth=1)
            if self.storage.add_frontier(
                run_id, url, parent_source_id=source_id, anchor="sitemap", relation="sitemap", depth=1, score=score
            ):
                added += 1
        return added


def _parse_sitemap(raw: bytes) -> tuple[list[str], list[str]]:
    if len(raw) > 5_000_000:
        return [], []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        # Some sites expose newline sitemap-like lists.
        text = raw.decode("utf-8", errors="replace")
        urls = re.findall(r"https?://[^\s<>\"]+", text)
        return urls[:2000], []
    tag = root.tag.casefold()
    locs = [node.text.strip() for node in root.iter() if node.tag.casefold().endswith("loc") and node.text]
    if tag.endswith("sitemapindex"):
        return [], locs[:100]
    return locs[:5000], []
