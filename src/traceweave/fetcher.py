from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import socket
import time
from dataclasses import dataclass, field
from io import BytesIO
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
class MediaLink:
    url: str
    kind: str = "image"
    alt: str = ""
    width: int | None = None
    height: int | None = None


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
    media: list[MediaLink] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class BinaryFetchResult:
    final_url: str
    status_code: int
    content_type: str
    raw: bytes
    content_hash: str


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
        return list(
            {item[4][0] for item in socket.getaddrinfo(host, parts.port or 443, type=socket.SOCK_STREAM)}
        )

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
        rel = (
            "citation"
            if any(
                k in (anchor + " " + href).casefold()
                for k in ("reference", "citation", "source", "report", "pdf")
            )
            else "link"
        )
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


def extract_media_links(raw: bytes, base_url: str, limit: int = 200) -> list[MediaLink]:
    """Extract public raster-image leads without downloading them."""
    soup = BeautifulSoup(raw, "html.parser")
    rows: list[MediaLink] = []
    seen: set[str] = set()

    def add(url_value: str, *, alt: str = "", width: str = "", height: str = "") -> None:
        url = canonicalize_url(urljoin(base_url, url_value.strip()))
        if not url.startswith(("http://", "https://")) or url in seen:
            return
        seen.add(url)
        try:
            parsed_width = int(width) if width else None
            parsed_height = int(height) if height else None
        except ValueError:
            parsed_width = parsed_height = None
        rows.append(
            MediaLink(url=url, alt=" ".join(alt.split())[:500], width=parsed_width, height=parsed_height)
        )

    for node in soup.find_all("meta", attrs={"content": True}):
        prop = str(node.get("property") or node.get("name") or "").casefold()
        if prop in {"og:image", "og:image:url", "twitter:image", "twitter:image:src"}:
            add(str(node.get("content") or ""), alt=str(node.get("alt") or "social preview"))
    for node in soup.find_all("img"):
        src = str(node.get("src") or node.get("data-src") or node.get("data-original") or "")
        if src and not src.startswith("data:"):
            add(
                src,
                alt=str(node.get("alt") or node.get("title") or ""),
                width=str(node.get("width") or ""),
                height=str(node.get("height") or ""),
            )
        if len(rows) >= limit:
            break
    return rows[:limit]


def extract_page_metadata(raw: bytes, base_url: str) -> dict[str, object]:
    """Extract bounded, evidence-preserving page metadata and JSON-LD."""
    soup = BeautifulSoup(raw, "html.parser")
    meta: dict[str, object] = {}
    html = soup.find("html")
    if html and html.get("lang"):
        meta["language"] = str(html.get("lang"))[:32]
    canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
    if canonical and canonical.get("href"):
        meta["canonical"] = canonicalize_url(urljoin(base_url, str(canonical.get("href"))))
    social: dict[str, str] = {}
    for node in soup.find_all("meta", attrs={"content": True})[:500]:
        key = str(node.get("property") or node.get("name") or "").casefold()
        if key in {
            "og:title",
            "og:description",
            "og:type",
            "og:site_name",
            "article:published_time",
            "article:modified_time",
            "article:author",
            "author",
            "date",
            "twitter:creator",
        }:
            social[key] = str(node.get("content") or "")[:2000]
    if social:
        meta["social"] = social
    json_ld: list[object] = []
    for node in soup.find_all("script", attrs={"type": "application/ld+json"})[:20]:
        try:
            value = __import__("json").loads(node.string or node.get_text() or "")
        except (ValueError, TypeError):
            continue
        json_ld.append(value)
    if json_ld:
        meta["json_ld"] = json_ld
    return meta


def _extract(raw: bytes, content_type: str, base_url: str) -> tuple[str, str, list[PageLink], list[str]]:
    ctype = content_type.lower()
    if "html" in ctype:
        return _extract_html(raw, base_url)
    if "pdf" in ctype or base_url.casefold().split("?", 1)[0].endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise FetchError("PDF extraction requires: pip install 'traceweave[stage4]'") from exc
        try:
            reader = PdfReader(BytesIO(raw), strict=False)
            pages = []
            for page in reader.pages[:500]:
                text = page.extract_text() or ""
                if text.strip():
                    pages.append(text.strip())
            title = ""
            if reader.metadata:
                title = str(getattr(reader.metadata, "title", "") or "")
            return "\n\n".join(pages), title, [], []
        except Exception as exc:
            raise FetchError(f"PDF parse failed: {exc}") from exc
    return raw.decode("utf-8", errors="replace"), "", [], []


def extract_payload(
    raw: bytes, content_type: str, base_url: str
) -> tuple[str, str, list[PageLink], list[str]]:
    """Extract stored/fetched bytes using the same bounded document parser as live fetches."""
    return _extract(raw, content_type, base_url)


class SafeFetcher:
    def __init__(
        self,
        *,
        timeout: float,
        max_bytes: int,
        user_agent: str,
        per_host_delay: float = 0.75,
        retries: int = 2,
    ):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.user_agent = user_agent
        self.per_host_delay = max(0.0, per_host_delay)
        self.retries = max(0, retries)
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._host_next: dict[str, float] = {}

    async def _pace(self, url: str) -> None:
        host = (urlsplit(url).hostname or "").casefold()
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._host_next.get(host, 0.0) - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._host_next[host] = time.monotonic() + self.per_host_delay

    async def fetch(
        self, url: str, max_redirects: int = 5, accept: str | None = None, max_bytes: int | None = None
    ) -> FetchResult:
        current = url
        headers = {
            "User-Agent": self.user_agent,
            "Accept": accept
            or "text/html,application/xhtml+xml,application/xml;q=0.8,text/plain;q=0.7,*/*;q=0.1",
        }
        byte_limit = int(max_bytes or self.max_bytes)
        async with httpx.AsyncClient(
            timeout=self.timeout, follow_redirects=False, headers=headers, trust_env=False
        ) as client:
            for _ in range(max_redirects + 1):
                await _validate_public_url(current)
                try:
                    await self._pace(current)
                    async with client.stream("GET", current) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                raise FetchError("Redirect without Location header")
                            current = urljoin(current, location)
                            continue
                        if response.status_code == 429 or 500 <= response.status_code <= 599:
                            retry_after = response.headers.get("retry-after", "")
                            try:
                                delay = min(30.0, max(0.5, float(retry_after)))
                            except ValueError:
                                delay = 1.0
                            if _ < self.retries:
                                await asyncio.sleep(delay * (2**_))
                                continue
                        response.raise_for_status()
                        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
                        if content_type and not (
                            content_type.startswith("text/")
                            or "html" in content_type
                            or "xml" in content_type
                            or "json" in content_type
                            or "pdf" in content_type
                        ):
                            raise FetchError(f"Unsupported content type: {content_type}")
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > byte_limit:
                                raise FetchError(f"Document exceeds {byte_limit} bytes")
                            chunks.append(chunk)
                        raw = b"".join(chunks)
                        final_url = str(response.url)
                        text, title, links, feeds = _extract(raw, content_type, final_url)
                        media = (
                            extract_media_links(raw, final_url) if "html" in content_type.casefold() else []
                        )
                        return FetchResult(
                            final_url=final_url,
                            status_code=response.status_code,
                            content_type=content_type,
                            raw=raw,
                            text=text,
                            title=title,
                            content_hash=hashlib.sha256(raw).hexdigest(),
                            simhash=simhash64(text),
                            links=links,
                            feeds=feeds,
                            media=media,
                            metadata=extract_page_metadata(raw, final_url)
                            if "html" in content_type.casefold()
                            else {},
                        )
                except httpx.HTTPError as exc:
                    raise FetchError(str(exc)) from exc
        raise FetchError("Too many redirects")

    async def fetch_binary(
        self,
        url: str,
        *,
        max_bytes: int,
        allowed_content_types: tuple[str, ...] = ("image/jpeg", "image/png", "image/webp", "image/gif"),
        max_redirects: int = 5,
    ) -> BinaryFetchResult:
        current = url
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "image/avif,image/webp,image/png,image/jpeg,image/gif;q=0.8",
        }
        async with httpx.AsyncClient(
            timeout=self.timeout, follow_redirects=False, headers=headers, trust_env=False
        ) as client:
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
                        content_type = (
                            response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
                        )
                        if content_type not in allowed_content_types:
                            raise FetchError(f"Unsupported media content type: {content_type or 'unknown'}")
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > max_bytes:
                                raise FetchError(f"Media exceeds {max_bytes} bytes")
                            chunks.append(chunk)
                        raw = b"".join(chunks)
                        return BinaryFetchResult(
                            final_url=str(response.url),
                            status_code=response.status_code,
                            content_type=content_type,
                            raw=raw,
                            content_hash=hashlib.sha256(raw).hexdigest(),
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
            raise FetchError(
                "Browser fallback requires: pip install 'traceweave[browser]' && crawl4ai-setup"
            ) from exc
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
            final_url=final_url,
            status_code=200,
            content_type="text/html",
            raw=html,
            text=text,
            title=title,
            content_hash=hashlib.sha256(html).hexdigest(),
            simhash=simhash64(text),
            links=links,
            feeds=feeds,
            media=extract_media_links(html, final_url),
            metadata=extract_page_metadata(html, final_url),
        )


class CloudflareBrowserFetcher:
    """Quota-aware Cloudflare Browser Rendering fallback for public pages only."""

    def __init__(self, credentials: list[tuple[str, str]], *, timeout: float, max_bytes: int):
        self.credentials = [(a, t) for a, t in credentials if a and t]
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._cursor = 0

    async def fetch(self, url: str) -> FetchResult:
        await _validate_public_url(url)
        if not self.credentials:
            raise FetchError("Cloudflare Browser Rendering is not configured")
        errors: list[str] = []
        for offset in range(len(self.credentials)):
            idx = (self._cursor + offset) % len(self.credentials)
            account, token = self.credentials[idx]
            endpoint = f"https://api.cloudflare.com/client/v4/accounts/{account}/browser-rendering/markdown"
            try:
                async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                    response = await client.post(
                        endpoint,
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        json={
                            "url": url,
                            "gotoOptions": {"waitUntil": "domcontentloaded", "timeout": 45000},
                            "rejectResourceTypes": ["font", "media"],
                        },
                    )
                if response.status_code in {401, 403, 429}:
                    errors.append(f"account-{idx + 1}:HTTP {response.status_code}")
                    continue
                response.raise_for_status()
                body = response.json()
                markdown = str(body.get("result") or "")
                raw = markdown.encode("utf-8")
                if len(raw) > self.max_bytes:
                    raise FetchError(f"Cloudflare browser document exceeds {self.max_bytes} bytes")
                self._cursor = (idx + 1) % len(self.credentials)
                return FetchResult(
                    final_url=url,
                    status_code=200,
                    content_type="text/markdown",
                    raw=raw,
                    text=markdown,
                    title="",
                    content_hash=hashlib.sha256(raw).hexdigest(),
                    simhash=simhash64(markdown),
                    metadata={"rendered_by": "cloudflare-browser-rendering", "account_slot": idx + 1},
                )
            except (httpx.HTTPError, ValueError) as exc:
                errors.append(f"account-{idx + 1}:{type(exc).__name__}")
        raise FetchError("Cloudflare Browser Rendering failed: " + ", ".join(errors))
