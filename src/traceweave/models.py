from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ResearchMode = Literal["quick", "standard", "deep"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResearchSpec(BaseModel):
    topic: str = Field(min_length=2, max_length=500)
    angle: str = Field(default="", max_length=500)
    mode: ResearchMode = "standard"
    language: str = Field(default="all", max_length=32)
    max_rounds: int | None = Field(default=None, ge=1, le=8)
    max_results_per_query: int = Field(default=8, ge=1, le=30)
    fetch_top_per_query: int = Field(default=4, ge=0, le=12)

    @field_validator("topic", "angle")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return " ".join(value.split())

    def resolved_rounds(self) -> int:
        if self.max_rounds is not None:
            return self.max_rounds
        return {"quick": 1, "standard": 2, "deep": 3}[self.mode]


class Plan(BaseModel):
    objective: str
    focus: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    rationale: str = ""

    @field_validator("queries")
    @classmethod
    def clean_queries(cls, values: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for value in values:
            q = " ".join(value.split()).strip()
            key = q.casefold()
            if q and key not in seen:
                out.append(q)
                seen.add(key)
        return out[:12]


class SearchResult(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""
    engine: str = "unknown"
    category: str = "web"
    published_at: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class SourceView(BaseModel):
    id: int
    url: str
    canonical_url: str
    title: str
    domain: str
    snippet: str = ""
    search_query: str = ""
    rank: int = 0
    engine: str = "unknown"
    category: str = "web"
    published_at: str | None = None
    discovered_at: str = Field(default_factory=utc_now)
    fetched: bool = False
    text_excerpt: str = ""


class ProgressEvent(BaseModel):
    kind: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    ts: str = Field(default_factory=utc_now)
