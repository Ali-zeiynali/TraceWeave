from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CredentialConfig:
    id: str
    token_env: str
    enabled: bool = True

    def token(self) -> str:
        return os.getenv(self.token_env, "").strip()


@dataclass(slots=True)
class ModelConfig:
    id: str
    name: str
    tasks: set[str] = field(default_factory=lambda: {"*"})
    capabilities: set[str] = field(default_factory=set)
    credentials: set[str] = field(default_factory=set)
    priority: int = 100
    weight: float = 1.0
    temperature: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProviderConfig:
    id: str
    driver: str
    base_url: str
    enabled: bool
    credentials: list[CredentialConfig]
    models: list[ModelConfig]
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class RouterFileConfig:
    providers: list[ProviderConfig]
