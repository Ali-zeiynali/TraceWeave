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
    max_rounds: int | None = Field(default=None, ge=1, le=10)
    max_results_per_query: int = Field(default=8, ge=1, le=40)
    fetch_top_per_query: int = Field(default=4, ge=0, le=16)
    max_depth: int | None = Field(default=None, ge=0, le=5)
    max_frontier_pages: int | None = Field(default=None, ge=0, le=500)

    @field_validator("topic", "angle")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return " ".join(value.split())

    def resolved_rounds(self) -> int:
        if self.max_rounds is not None:
            return self.max_rounds
        return {"quick": 1, "standard": 2, "deep": 4}[self.mode]

    def resolved_depth(self) -> int:
        if self.max_depth is not None:
            return self.max_depth
        return {"quick": 0, "standard": 1, "deep": 3}[self.mode]

    def resolved_frontier_pages(self) -> int:
        if self.max_frontier_pages is not None:
            return self.max_frontier_pages
        return {"quick": 0, "standard": 8, "deep": 30}[self.mode]


class Plan(BaseModel):
    objective: str
    focus: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    rationale: str = ""
    gaps: list[str] = Field(default_factory=list)
    source_classes: list[str] = Field(default_factory=list)

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
        return out[:14]


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
    relevance: float | None = None
    importance: float | None = None
    novelty: float | None = None
    authority: float | None = None
    duplicate_of: int | None = None
    family_key: str = ""


class TriageResult(BaseModel):
    relevance: float = Field(ge=0, le=100)
    importance: float = Field(ge=0, le=100)
    novelty: float = Field(ge=0, le=100)
    authority: float = Field(ge=0, le=100)
    rationale: str = ""
    topics: list[str] = Field(default_factory=list)
    leads: list[str] = Field(default_factory=list)


class ExtractedClaim(BaseModel):
    claim: str = Field(min_length=3, max_length=1200)
    evidence_quote: str = Field(min_length=1, max_length=3000)
    subject: str = ""
    predicate: str = ""
    object: str = ""
    observed_at: str | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)


class ProgressEvent(BaseModel):
    kind: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    ts: str = Field(default_factory=utc_now)
