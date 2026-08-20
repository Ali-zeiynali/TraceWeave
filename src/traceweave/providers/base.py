from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class LLMError(RuntimeError):
    pass


@dataclass(slots=True)
class ProviderFailure(LLMError):
    message: str
    kind: str = "unknown"
    status_code: int | None = None
    retry_after: float | None = None
    headers: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


class LLMProvider(Protocol):
    name: str

    async def json(
        self, *, system: str, user: str, task: str = "general", run_id: str | None = None
    ) -> dict: ...
    async def text(
        self, *, system: str, user: str, task: str = "general", run_id: str | None = None
    ) -> str: ...
    async def vision_json(
        self, *, system: str, user: str, image: bytes, media_type: str, run_id: str
    ) -> dict: ...
