from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from traceweave.config import Settings
from traceweave.providers.catalog import ModelCatalog
from traceweave.providers.presets import providers_from_env


from traceweave.providers.types import CredentialConfig, ModelConfig, ProviderConfig, RouterFileConfig

def _strings(value: Any, default: list[str] | None = None) -> set[str]:
    if value is None:
        return set(default or [])
    if isinstance(value, str):
        return {value}
    return {str(v) for v in value}


def load_provider_config(settings: Settings) -> RouterFileConfig:
    path = Path(settings.provider_config)
    catalog = ModelCatalog(settings.data_dir / "catalog" / "models.json", settings.provider_catalog_ttl_seconds)
    # Built-in environment presets make the common path zero-config: API keys in .env are enough.
    # Explicit providers.toml entries are merged by provider id and take precedence.
    providers: list[ProviderConfig] = providers_from_env(catalog_models=catalog.load())
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
            explicit = ProviderConfig(
                id=str(p["id"]), driver=str(p.get("driver", "openai_compat")),
                base_url=str(p.get("base_url", "")).rstrip("/"), enabled=bool(p.get("enabled", True)),
                credentials=creds, models=models,
                headers={str(k): str(v) for k, v in (p.get("headers") or {}).items()},
            )
            providers = [existing for existing in providers if existing.id != explicit.id]
            providers.append(explicit)

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
