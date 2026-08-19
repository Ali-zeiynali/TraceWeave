from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from traceweave.config import Settings


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


def _strings(value: Any, default: list[str] | None = None) -> set[str]:
    if value is None:
        return set(default or [])
    if isinstance(value, str):
        return {value}
    return {str(v) for v in value}


def load_provider_config(settings: Settings) -> RouterFileConfig:
    path = Path(settings.provider_config)
    providers: list[ProviderConfig] = []
    if path.exists():
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        for p in raw.get("providers", []):
            creds = [
                CredentialConfig(
                    id=str(c["id"]), token_env=str(c["token_env"]), enabled=bool(c.get("enabled", True))
                )
                for c in p.get("credentials", [])
            ]
            models = []
            for m in p.get("models", []):
                known = {"id", "name", "tasks", "capabilities", "credentials", "priority", "weight", "temperature"}
                models.append(ModelConfig(
                    id=str(m["id"]), name=str(m["name"]), tasks=_strings(m.get("tasks"), ["*"]),
                    capabilities=_strings(m.get("capabilities")), credentials=_strings(m.get("credentials")),
                    priority=int(m.get("priority", 100)), weight=float(m.get("weight", 1.0)),
                    temperature=float(m["temperature"]) if "temperature" in m else None,
                    extra={k: v for k, v in m.items() if k not in known},
                ))
            providers.append(ProviderConfig(
                id=str(p["id"]), driver=str(p.get("driver", "openai_compat")),
                base_url=str(p.get("base_url", "")).rstrip("/"), enabled=bool(p.get("enabled", True)),
                credentials=creds, models=models,
                headers={str(k): str(v) for k, v in (p.get("headers") or {}).items()},
            ))

    # Backward compatibility with Stage 1.
    if not providers and settings.api_base and settings.api_key and settings.model:
        legacy_env = "TRACEWEAVE_API_KEY"
        os.environ.setdefault(legacy_env, settings.api_key)
        providers.append(ProviderConfig(
            id="legacy", driver="openai_compat", base_url=settings.api_base.rstrip("/"), enabled=True,
            credentials=[CredentialConfig(id="legacy-key", token_env=legacy_env)],
            models=[ModelConfig(id="legacy-model", name=settings.model, tasks={"*"}, priority=100)],
        ))
    return RouterFileConfig(providers=providers)
