from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from traceweave.utils import canonicalize_url, is_public_ip, simhash64


class FetchError(RuntimeError):
    pass


@dataclass(slots=True)
class PageLink:
    url: str
    anchor: str = ""
    relation: str = "link"


@dataclass(slots=True)
class FetchResult:
    final_url: str
    status_code: int
    content_type: str
    raw: bytes
    text: str
    title: str
    content_hash: str
    simhash: str = ""
    links: list[PageLink] = field(default_factory=list)
    feeds: list[str] = field(default_factory=list)


async def _validate_public_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise FetchError("Only public http/https URLs are allowed")
    host = parts.hostname
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not is_public_ip(host):
            raise FetchError("Private/reserved network targets are blocked")
        return

    def resolve() -> list[str]:
        return list({item[4][0] for item in socket.getaddrinfo(host, parts.port or 443, type=socket.SOCK_STREAM)})

    try:
        addresses = await asyncio.to_thread(resolve)
    except socket.gaierror as exc:
        raise FetchError(f"DNS resolution failed for {host}") from exc
    if not addresses or any(not is_public_ip(ip) for ip in addresses):
        raise FetchError("Host resolves to a private/reserved network target")


def _extract_html(raw: bytes, base_url: str) -> tuple[str, str, list[PageLink], list[str]]:
    soup = BeautifulSoup(raw, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    links: list[PageLink] = []
    seen: set[str] = set()
    for node in soup.find_all("a", href=True)[:1500]:
        href = str(node.get("href", "")).strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "data:")):
            continue
        url = canonicalize_url(urljoin(base_url, href))
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        anchor = " ".join(node.get_text(" ", strip=True).split())[:500]
        rel = "citation" if any(k in (anchor + " " + href).casefold() for k in ("reference", "citation", "source", "report", "pdf")) else "link"
        links.append(PageLink(url=url, anchor=anchor, relation=rel))
        if len(links) >= 500:
            break
    feeds: list[str] = []
    for node in soup.find_all("link", href=True):
        rel = " ".join(node.get("rel") or []).casefold()
        typ = str(node.get("type") or "").casefold()
        if "alternate" in rel and any(x in typ for x in ("rss", "atom", "xml")):
            url = canonicalize_url(urljoin(base_url, str(node["href"])))
            if url.startswith(("http://", "https://")) and url not in feeds:
                feeds.append(url)
    for tag in soup(["script", "style", "noscript", "svg", "template"]):
        tag.decompose()
    node = soup.find("article") or soup.find("main") or soup.body or soup
    lines = []
    for line in node.get_text("\n", strip=True).splitlines():
        clean = " ".join(line.split())
        if clean:
            lines.append(clean)
    return "\n".join(lines), title, links, feeds[:20]


def _extract(raw: bytes, content_type: str, base_url: str) -> tuple[str, str, list[PageLink], list[str]]:
    ctype = content_type.lower()
    if "html" in ctype:
        return _extract_html(raw, base_url)
    return raw.decode("utf-8", errors="replace"), "", [], []


class SafeFetcher:
    def __init__(self, *, timeout: float, max_bytes: int, user_agent: str):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.user_agent = user_agent

    async def fetch(self, url: str, max_redirects: int = 5, accept: str | None = None) -> FetchResult:
        current = url
        headers = {
            "User-Agent": self.user_agent,
            "Accept": accept or "text/html,application/xhtml+xml,application/xml;q=0.8,text/plain;q=0.7,*/*;q=0.1",
        }
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False, headers=headers, trust_env=False) as client:
            for _ in range(max_redirects + 1):
                await _validate_public_url(current)
                try:
                    async with client.stream("GET", current) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                raise FetchError("Redirect without Location header")
                            current = urljoin(current, location)
                            continue
                        response.raise_for_status()
                        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
                        if content_type and not (
                            content_type.startswith("text/") or "html" in content_type or "xml" in content_type or "json" in content_type
                        ):
                            raise FetchError(f"Unsupported content type: {content_type}")
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > self.max_bytes:
                                raise FetchError(f"Document exceeds {self.max_bytes} bytes")
                            chunks.append(chunk)
                        raw = b"".join(chunks)
                        final_url = str(response.url)
                        text, title, links, feeds = _extract(raw, content_type, final_url)
                        return FetchResult(
                            final_url=final_url, status_code=response.status_code, content_type=content_type,
                            raw=raw, text=text, title=title, content_hash=hashlib.sha256(raw).hexdigest(),
                            simhash=simhash64(text), links=links, feeds=feeds,
                        )
                except httpx.HTTPError as exc:
                    raise FetchError(str(exc)) from exc
        raise FetchError("Too many redirects")


class BrowserFetcher:
    """Optional Crawl4AI fallback for JS-heavy public pages."""

    def __init__(self, *, timeout: float, max_bytes: int):
        self.timeout = timeout
        self.max_bytes = max_bytes

    async def fetch(self, url: str) -> FetchResult:
        await _validate_public_url(url)
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
        except ImportError as exc:
            raise FetchError("Browser fallback requires: pip install 'traceweave[browser]' && crawl4ai-setup") from exc
        browser_config = BrowserConfig(headless=True, verbose=False)
        run_config = CrawlerRunConfig(page_timeout=int(self.timeout * 1000), verbose=False)
        try:
            async with AsyncWebCrawler(config=browser_config) as crawler:
                result = await crawler.arun(url=url, config=run_config)
        except Exception as exc:
            raise FetchError(f"Crawl4AI failed: {exc}") from exc
        html = (getattr(result, "html", "") or "").encode("utf-8", errors="replace")
        if len(html) > self.max_bytes:
            raise FetchError(f"Browser document exceeds {self.max_bytes} bytes")
        final_url = str(getattr(result, "url", url) or url)
        text, title, links, feeds = _extract_html(html, final_url)
        return FetchResult(
            final_url=final_url, status_code=200, content_type="text/html", raw=html, text=text,
            title=title, content_hash=hashlib.sha256(html).hexdigest(), simhash=simhash64(text), links=links, feeds=feeds,
        )
