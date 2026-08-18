from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from traceweave.utils import is_public_ip


class FetchError(RuntimeError):
    pass


@dataclass(slots=True)
class FetchResult:
    final_url: str
    status_code: int
    content_type: str
    raw: bytes
    text: str
    title: str
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
        return list({item[4][0] for item in socket.getaddrinfo(host, parts.port or 443, type=socket.SOCK_STREAM)})

    try:
        addresses = await asyncio.to_thread(resolve)
    except socket.gaierror as exc:
        raise FetchError(f"DNS resolution failed for {host}") from exc
    if not addresses or any(not is_public_ip(ip) for ip in addresses):
        raise FetchError("Host resolves to a private/reserved network target")


def _extract_text(raw: bytes, content_type: str) -> tuple[str, str]:
    if "html" not in content_type.lower():
        return raw.decode("utf-8", errors="replace"), ""
    soup = BeautifulSoup(raw, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for tag in soup(["script", "style", "noscript", "svg", "template"]):
        tag.decompose()
    node = soup.find("article") or soup.find("main") or soup.body or soup
    lines = []
    for line in node.get_text("\n", strip=True).splitlines():
        clean = " ".join(line.split())
        if clean:
            lines.append(clean)
    return "\n".join(lines), title


class SafeFetcher:
    def __init__(self, *, timeout: float, max_bytes: int, user_agent: str):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.user_agent = user_agent

    async def fetch(self, url: str, max_redirects: int = 5) -> FetchResult:
        current = url
        headers = {"User-Agent": self.user_agent, "Accept": "text/html,text/plain;q=0.9,*/*;q=0.2"}
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
                            content_type.startswith("text/") or "html" in content_type or "xml" in content_type
                        ):
                            raise FetchError(f"Unsupported Stage-1 content type: {content_type}")
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > self.max_bytes:
                                raise FetchError(f"Document exceeds {self.max_bytes} bytes")
                            chunks.append(chunk)
                        raw = b"".join(chunks)
                        text, title = _extract_text(raw, content_type)
                        return FetchResult(
                            final_url=str(response.url),
                            status_code=response.status_code,
                            content_type=content_type,
                            raw=raw,
                            text=text,
                            title=title,
                            content_hash=hashlib.sha256(raw).hexdigest(),
                        )
                except httpx.HTTPError as exc:
                    raise FetchError(str(exc)) from exc
        raise FetchError("Too many redirects")
