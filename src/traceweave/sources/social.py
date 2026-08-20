from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

from traceweave.models import SearchResult


class BlueskyPublicSource:
    def __init__(self, *, timeout: float = 20.0):
        self.timeout = timeout

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.get(
                "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts",
                params={"q": query, "limit": min(100, max(1, limit)), "sort": "latest"},
            )
            response.raise_for_status()
            payload = response.json()
        rows = []
        for post in payload.get("posts", [])[:limit]:
            author = post.get("author") or {}
            record = post.get("record") or {}
            uri = str(post.get("uri") or "")
            rkey = uri.rsplit("/", 1)[-1]
            handle = str(author.get("handle") or author.get("did") or "")
            if not handle or not rkey:
                continue
            text = str(record.get("text") or "")
            rows.append(
                SearchResult(
                    url=f"https://bsky.app/profile/{handle}/post/{rkey}",
                    title=f"{author.get('displayName') or handle} on Bluesky",
                    snippet=text[:1000],
                    engine="bluesky",
                    category="public-social",
                    published_at=str(record.get("createdAt") or post.get("indexedAt") or "") or None,
                    raw=post,
                )
            )
        return rows


class TelegramPublicSource:
    """Official MTProto user session restricted to globally searchable public messages."""

    def __init__(self, *, session_path: Path, api_id: int, api_hash: str):
        self.session_path = Path(session_path)
        self.api_id = api_id
        self.api_hash = api_hash

    @classmethod
    def from_env(cls) -> TelegramPublicSource | None:
        api_id = os.getenv("TELEGRAM_API_ID", "").strip()
        api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
        session = os.getenv("TELEGRAM_SESSION_PATH", ".traceweave/sessions/telegram").strip()
        if not api_id or not api_hash:
            return None
        try:
            parsed_id = int(api_id)
        except ValueError:
            return None
        return cls(session_path=Path(session), api_id=parsed_id, api_hash=api_hash)

    async def search(self, query: str, limit: int = 20) -> list[SearchResult]:
        try:
            from telethon import TelegramClient, functions, types
        except ImportError as exc:
            raise RuntimeError("Telegram support requires: pip install 'traceweave[social]'") from exc
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        client = TelegramClient(str(self.session_path), self.api_id, self.api_hash)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise RuntimeError(
                    "Telegram session is not authorized. Authorize it interactively once; unattended research never requests login codes."
                )
            result = await client(
                functions.messages.SearchGlobalRequest(
                    q=query,
                    filter=types.InputMessagesFilterEmpty(),
                    min_date=None,
                    max_date=None,
                    offset_rate=0,
                    offset_peer=types.InputPeerEmpty(),
                    offset_id=0,
                    limit=min(100, max(1, limit)),
                )
            )
            peers: dict[int, Any] = {}
            for peer in [*(getattr(result, "chats", []) or []), *(getattr(result, "users", []) or [])]:
                peer_id = getattr(peer, "id", None)
                if peer_id is not None:
                    peers[int(peer_id)] = peer
            rows: list[SearchResult] = []
            for message in getattr(result, "messages", []) or []:
                peer_id = getattr(getattr(message, "peer_id", None), "channel_id", None)
                peer = peers.get(int(peer_id)) if peer_id is not None else None
                username = str(getattr(peer, "username", "") or "")
                # No public username means the message cannot be independently opened as public evidence.
                if not username:
                    continue
                message_id = int(getattr(message, "id", 0) or 0)
                text = str(getattr(message, "message", "") or "")
                date = getattr(message, "date", None)
                rows.append(
                    SearchResult(
                        url=f"https://t.me/{username}/{message_id}",
                        title=f"Telegram: {getattr(peer, 'title', None) or username}",
                        snippet=text[:1000],
                        engine="telegram-official",
                        category="public-social",
                        published_at=date.isoformat() if date else None,
                        raw={
                            "channel": username,
                            "message_id": message_id,
                            "text": text,
                            "date": date.isoformat() if date else None,
                        },
                    )
                )
            return rows[:limit]
        finally:
            await client.disconnect()

    async def authorize(self) -> str:
        """Interactive, operator-triggered one-time session authorization."""
        try:
            from telethon import TelegramClient
        except ImportError as exc:
            raise RuntimeError("Telegram support requires: pip install 'traceweave[social]'") from exc
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        client = TelegramClient(str(self.session_path), self.api_id, self.api_hash)
        try:
            await client.start()
            me = await client.get_me()
            return str(getattr(me, "username", None) or getattr(me, "id", "authorized"))
        finally:
            await client.disconnect()


class InstagramOfficialSource:
    """Official Instagram hashtag discovery for an operator-authorized professional account."""

    def __init__(self, *, access_token: str, user_id: str, graph_version: str, timeout: float):
        self.access_token = access_token
        self.user_id = user_id
        self.base = f"https://graph.facebook.com/{graph_version.strip('/')}"
        self.timeout = timeout

    @classmethod
    def from_env(cls, *, timeout: float) -> InstagramOfficialSource | None:
        token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
        user_id = os.getenv("INSTAGRAM_USER_ID", "").strip()
        if not token or not user_id:
            return None
        return cls(
            access_token=token,
            user_id=user_id,
            graph_version=os.getenv("META_GRAPH_VERSION", "v23.0").strip() or "v23.0",
            timeout=timeout,
        )

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        hashtag = "".join(ch for ch in query.lstrip("#").split()[0] if ch.isalnum() or ch == "_")
        if len(hashtag) < 2:
            return []
        params = {"user_id": self.user_id, "q": hashtag, "access_token": self.access_token}
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.get(f"{self.base}/ig_hashtag_search", params=params)
            response.raise_for_status()
            ids = response.json().get("data", [])
            if not ids:
                return []
            hashtag_id = str(ids[0].get("id") or "")
            response = await client.get(
                f"{self.base}/{hashtag_id}/recent_media",
                params={
                    "user_id": self.user_id,
                    "fields": "id,caption,media_type,permalink,timestamp,username,children{id,media_type,media_url}",
                    "limit": str(min(50, max(1, limit))),
                    "access_token": self.access_token,
                },
            )
            response.raise_for_status()
            media = response.json().get("data", [])
        return [
            SearchResult(
                url=str(item.get("permalink") or ""),
                title=f"Instagram: @{item.get('username') or 'public post'}",
                snippet=str(item.get("caption") or "")[:1000],
                engine="instagram-official",
                category="public-social",
                published_at=str(item.get("timestamp") or "") or None,
                raw=item,
            )
            for item in media[:limit]
            if item.get("permalink")
        ]


class PublicSocialSources:
    def __init__(
        self,
        *,
        timeout: float = 20.0,
        bluesky_enabled: bool = True,
        telegram_enabled: bool = False,
        instagram_enabled: bool = False,
    ):
        self.bluesky = BlueskyPublicSource(timeout=timeout) if bluesky_enabled else None
        self.telegram = TelegramPublicSource.from_env() if telegram_enabled else None
        self.instagram = InstagramOfficialSource.from_env(timeout=timeout) if instagram_enabled else None

    async def search(self, query: str, limit: int = 10) -> tuple[list[SearchResult], list[str]]:
        rows: list[SearchResult] = []
        errors: list[str] = []
        for name, source in (
            ("bluesky", self.bluesky),
            ("instagram", self.instagram),
            ("telegram", self.telegram),
        ):
            if source is None:
                continue
            try:
                rows.extend(await source.search(query, limit))
            except Exception as exc:
                errors.append(f"{name}:{type(exc).__name__}:{exc}"[:500])
        return rows, errors
