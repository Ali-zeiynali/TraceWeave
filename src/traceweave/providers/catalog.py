from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx


class ModelCatalog:
    """Credential-scoped model catalog cache.

    Shape on disk: providers -> provider_id -> credential_id -> [normalized models].
    Raw API tokens are never stored.
    """
    def __init__(self, path: Path, ttl_seconds: int = 21600):
        self.path = path
        self.ttl_seconds = ttl_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def metadata(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def load(self) -> dict[str, dict[str, list[dict[str, Any]]]]:
        providers = self.metadata().get("providers", {})
        return providers if isinstance(providers, dict) else {}

    def stale(self, provider_id: str, credential_id: str) -> bool:
        stamps = self.metadata().get("updated_at", {})
        key = f"{provider_id}:{credential_id}"
        try:
            return time.time() - float(stamps.get(key, 0)) > self.ttl_seconds
        except (AttributeError, TypeError, ValueError):
            return True

    async def sync_provider(self, provider_id: str, credential_id: str, *, token: str = "", base_url: str, timeout: float = 20) -> list[dict[str, Any]]:
        base = base_url.rstrip("/")
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.get(f"{base}/models", headers=headers)
            response.raise_for_status(); body = response.json()
        rows = body.get("data", body) if isinstance(body, dict) else body
        if not isinstance(rows, list):
            raise ValueError(f"{provider_id} /models returned an unsupported shape")
        normalized = [self._normalize(provider_id, row) for row in rows if isinstance(row, dict)]
        normalized = [row for row in normalized if row.get("id")]
        current = self.metadata()
        providers = current.get("providers", {}) if isinstance(current.get("providers"), dict) else {}
        per_provider = providers.get(provider_id, {}) if isinstance(providers.get(provider_id), dict) else {}
        per_provider[credential_id] = normalized; providers[provider_id] = per_provider
        stamps = current.get("updated_at", {}) if isinstance(current.get("updated_at"), dict) else {}
        stamps[f"{provider_id}:{credential_id}"] = time.time()
        payload = {"version": 2, "updated_at": stamps, "providers": providers}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"); tmp.replace(self.path)
        return normalized

    @staticmethod
    def _normalize(provider_id: str, row: dict[str, Any]) -> dict[str, Any]:
        model_id = str(row.get("id") or row.get("name") or "").strip()
        is_free: bool | None = None
        if provider_id == "openrouter":
            pricing = row.get("pricing") if isinstance(row.get("pricing"), dict) else {}
            try:
                is_free = float(pricing.get("prompt", "nan")) == 0 and float(pricing.get("completion", "nan")) == 0
            except (TypeError, ValueError):
                is_free = model_id.endswith(":free")
            is_free = bool(is_free or model_id.endswith(":free") or model_id == "openrouter/free")
        elif provider_id == "zenmux":
            is_free = model_id.endswith("-free") or "free" in str(row.get("name", "")).casefold()
            pricing = row.get("pricing") if isinstance(row.get("pricing"), dict) else {}
            if pricing:
                try:
                    is_free = is_free or (float(pricing.get("input", pricing.get("prompt", "nan"))) == 0 and float(pricing.get("output", pricing.get("completion", "nan"))) == 0)
                except (TypeError, ValueError):
                    pass
        return {"id": model_id, "is_free": is_free, "raw": row}
