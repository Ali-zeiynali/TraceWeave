from __future__ import annotations

from typing import Protocol


class LLMError(RuntimeError):
    pass


class LLMProvider(Protocol):
    name: str

    async def json(self, *, system: str, user: str) -> dict: ...
    async def text(self, *, system: str, user: str) -> str: ...
