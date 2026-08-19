from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SpecialistResult:
    url: str
    title: str = ""
    snippet: str = ""
    engine: str = "specialist"
    category: str = "specialist"
    published_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
