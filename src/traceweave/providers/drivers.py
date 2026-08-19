from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any

import httpx

from traceweave.providers.base import ProviderFailure


@dataclass(slots=True)
class Deployment:
    provider_id: str
    credential_id: str
    token: str
    model_id: str
    model_name: str
    driver: str
    base_url: str
    tasks: set[str]
    capabilities: set[str]
    priority: int
    weight: float
    temperature: float | None
    headers: dict[str, str]
    extra: dict[str, Any]

    @property
    def credential_key(self) -> str:
        return f"{self.provider_id}:{self.credential_id}"

    @property
    def deployment_key(self) -> str:
        return f"{self.provider_id}:{self.credential_id}:{self.model_id}"


def parse_retry_after(headers: dict[str, str]) -> float | None:
    lower = {str(k).lower(): str(v) for k, v in headers.items()}
    raw = lower.get("retry-after")
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    candidates: list[float] = []
    for key in ("x-ratelimit-reset", "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
        value = lower.get(key)
        if not value:
            continue
        parsed = _duration_seconds(value)
        if parsed is not None:
            candidates.append(parsed)
    return max(candidates) if candidates else None


def _duration_seconds(value: str) -> float | None:
    value = value.strip().lower()
    try:
        number = float(value)
        # Huge values are usually epoch timestamps and are intentionally ignored here.
        return number if number < 86400 * 30 else None
    except ValueError:
        pass
    total = 0.0
    found = False
    for number, unit in re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*(ms|s|m|h)", value):
        found = True
        mult = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}[unit]
        total += float(number) * mult
    return total if found else None


def classify_status(status: int | None) -> str:
    if status in {401, 403}:
        return "auth"
    if status == 429:
        return "rate_limit"
    if status in {400, 404, 405, 422}:
        return "model_or_request"
    if status is not None and 500 <= status <= 599:
        return "upstream"
    return "unknown"


async def call_openai_compat(
    deployment: Deployment, *, system: str, user: str, timeout: float, temperature: float
) -> str:
    if not deployment.base_url:
        raise ProviderFailure("OpenAI-compatible deployment has no base_url", kind="configuration")
    url = f"{deployment.base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": deployment.model_name,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": deployment.temperature if deployment.temperature is not None else temperature,
    }
    payload.update(deployment.extra.get("request", {}))
    headers = {"Authorization": f"Bearer {deployment.token}", "Content-Type": "application/json", **deployment.headers}
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise ProviderFailure(f"timeout calling {deployment.provider_id}", kind="timeout") from exc
    except httpx.HTTPError as exc:
        raise ProviderFailure(f"network error calling {deployment.provider_id}: {exc}", kind="network") from exc
    h = dict(response.headers)
    if response.is_error:
        try:
            detail = response.json()
        except ValueError:
            detail = response.text[:500]
        raise ProviderFailure(
            f"HTTP {response.status_code}: {detail}", kind=classify_status(response.status_code),
            status_code=response.status_code, retry_after=parse_retry_after(h), headers=h,
        )
    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise ProviderFailure("Malformed chat-completions response", kind="malformed") from exc
    if isinstance(content, list):
        content = "\n".join(str(x.get("text", "")) if isinstance(x, dict) else str(x) for x in content)
    return str(content)


async def call_litellm(
    deployment: Deployment, *, system: str, user: str, timeout: float, temperature: float
) -> str:
    try:
        import litellm
    except ImportError as exc:
        raise ProviderFailure(
            "LiteLLM driver requested but LiteLLM is not installed. Run: pip install 'traceweave[providers]'",
            kind="configuration",
        ) from exc
    kwargs: dict[str, Any] = {
        "model": deployment.model_name,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "api_key": deployment.token,
        "timeout": timeout,
        "temperature": deployment.temperature if deployment.temperature is not None else temperature,
    }
    if deployment.base_url:
        kwargs["api_base"] = deployment.base_url
    kwargs.update(deployment.extra.get("litellm", {}))
    try:
        response = await litellm.acompletion(**kwargs)
        content = response.choices[0].message.content
        if isinstance(content, list):
            content = "\n".join(str(getattr(x, "text", x)) for x in content)
        return str(content)
    except asyncio.TimeoutError as exc:
        raise ProviderFailure(f"timeout calling {deployment.provider_id}", kind="timeout") from exc
    except Exception as exc:  # LiteLLM normalizes many provider exception classes dynamically.
        status = getattr(exc, "status_code", None)
        response = getattr(exc, "response", None)
        headers = dict(getattr(response, "headers", {}) or {})
        raise ProviderFailure(
            str(exc), kind=classify_status(status), status_code=status,
            retry_after=parse_retry_after(headers), headers=headers,
        ) from exc
