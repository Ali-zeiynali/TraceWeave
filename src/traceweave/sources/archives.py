from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(slots=True)
class ArchiveCapture:
    engine: str
    original_url: str
    capture_url: str
    captured_at: str
    mime: str = ""
    status: int | None = None
    digest: str = ""
    raw: dict[str, Any] | None = None


class WaybackSource:
    def __init__(self, *, timeout: float = 25):
        self.timeout = timeout

    async def captures(self, url: str, limit: int = 3) -> list[ArchiveCapture]:
        params = {
            "url": url,
            "output": "json",
            "fl": "timestamp,original,mimetype,statuscode,digest",
            "collapse": "digest",
            "limit": str(max(2, limit * 4)),
            "filter": "statuscode:200",
        }
        async with httpx.AsyncClient(
            timeout=self.timeout, trust_env=False, headers={"User-Agent": "TraceWeave/0.5"}
        ) as client:
            r = await client.get("https://web.archive.org/cdx/search/cdx", params=params)
            r.raise_for_status()
            body = r.json()
        if not isinstance(body, list) or len(body) < 2:
            return []
        header = body[0]
        rows = [dict(zip(header, row, strict=False)) for row in body[1:] if isinstance(row, list)]
        selected = _spread(rows, limit)
        out = []
        for row in selected:
            ts = str(row.get("timestamp") or "")
            original = str(row.get("original") or url)
            out.append(
                ArchiveCapture(
                    engine="wayback",
                    original_url=original,
                    capture_url=f"https://web.archive.org/web/{ts}id_/{original}",
                    captured_at=ts,
                    mime=str(row.get("mimetype") or ""),
                    status=_int(row.get("statuscode")),
                    digest=str(row.get("digest") or ""),
                    raw=row,
                )
            )
        return out


class CommonCrawlSource:
    def __init__(self, *, timeout: float = 25):
        self.timeout = timeout
        self._index: dict[str, Any] | None = None

    async def latest_index(self) -> dict[str, Any]:
        if self._index:
            return self._index
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            r = await client.get("https://index.commoncrawl.org/collinfo.json")
            r.raise_for_status()
            rows = r.json()
        if not rows:
            raise RuntimeError("Common Crawl returned no indexes")
        self._index = rows[0]
        return self._index

    async def captures(self, url: str, limit: int = 3) -> list[ArchiveCapture]:
        index = await self.latest_index()
        api = str(index.get("cdx-api") or index.get("cdx_api") or "")
        if not api:
            raise RuntimeError("Common Crawl index lacks cdx-api")
        params = {"url": url, "output": "json", "filter": "status:200", "collapse": "digest"}
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            r = await client.get(api, params=params)
            if r.status_code == 404:
                return []
            r.raise_for_status()
        rows = []
        for line in r.text.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        selected = _spread(rows, limit)
        return [
            ArchiveCapture(
                engine="commoncrawl",
                original_url=str(x.get("url") or url),
                capture_url=f"ccwarc://{x.get('filename')}#{x.get('offset')}:{x.get('length')}",
                captured_at=str(x.get("timestamp") or ""),
                mime=str(x.get("mime") or x.get("mime-detected") or ""),
                status=_int(x.get("status")),
                digest=str(x.get("digest") or ""),
                raw=x,
            )
            for x in selected
        ]

    async def fetch_capture(
        self, capture: ArchiveCapture, *, max_bytes: int = 20_000_000
    ) -> tuple[bytes, str]:
        row = capture.raw or {}
        filename, offset, length = (
            str(row.get("filename") or ""),
            _int(row.get("offset")),
            _int(row.get("length")),
        )
        if not filename or offset is None or length is None or length <= 0 or length > max_bytes:
            raise RuntimeError("Invalid or oversized Common Crawl WARC range")
        headers = {"Range": f"bytes={offset}-{offset + length - 1}", "User-Agent": "TraceWeave/0.5"}
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False, headers=headers) as client:
            r = await client.get(f"https://data.commoncrawl.org/{filename}")
            r.raise_for_status()
            payload = r.content
        if payload[:2] == b"\x1f\x8b":
            payload = gzip.decompress(payload)
        # A range normally contains one WARC response record. Keep parsing dependency-free:
        # locate the embedded HTTP response and return its body; the raw WARC bytes remain available in metadata if needed later.
        marker = payload.find(b"HTTP/")
        if marker < 0:
            return payload, "application/octet-stream"
        header_end = payload.find(b"\r\n\r\n", marker)
        if header_end < 0:
            return payload[marker:], "application/octet-stream"
        headers_blob = payload[marker:header_end].decode("latin-1", errors="replace")
        ctype = ""
        for line in headers_blob.splitlines():
            if line.lower().startswith("content-type:"):
                ctype = line.split(":", 1)[1].strip().split(";", 1)[0]
        return payload[header_end + 4 :], ctype


def _spread(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(rows) <= limit:
        return rows
    # Oldest + newest + evenly spread middle captures provide more historical information than N adjacent snapshots.
    idx = {0, len(rows) - 1}
    if limit > 2:
        for i in range(1, limit - 1):
            idx.add(round(i * (len(rows) - 1) / (limit - 1)))
    return [rows[i] for i in sorted(idx)[:limit]]


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
