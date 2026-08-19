from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from dataclasses import dataclass

from traceweave.config import Settings
from traceweave.providers.base import LLMError, ProviderFailure
from traceweave.providers.config import load_provider_config
from traceweave.providers.drivers import Deployment, call_litellm, call_openai_compat
from traceweave.storage import Storage
from traceweave.utils import extract_first_json_object


_REFUSAL_MARKERS = (
    "i can't assist with", "i cannot assist with", "i can't help with", "i cannot help with",
    "i'm unable to assist", "i am unable to assist", "cannot comply", "can't comply",
    "抱歉，我不能", "无法回答", "不能回答", "无法提供",
)


@dataclass(slots=True)
class CandidateView:
    deployment: Deployment
    score: float
    credential_cooldown: float
    deployment_cooldown: float
    task_cooldown: float


class ModelRouter:
    """Task-aware multi-provider router with credential-, deployment-, and task-level health.

    The raw API token is never persisted. Health is keyed by the configured credential id.
    """

    name = "traceweave-router"

    def __init__(self, settings: Settings, storage: Storage):
        self.settings = settings
        self.storage = storage
        self.deployments = self._build_deployments()

    def _build_deployments(self) -> list[Deployment]:
        cfg = load_provider_config(self.settings)
        deployments: list[Deployment] = []
        for provider in cfg.providers:
            if not provider.enabled:
                continue
            for credential in provider.credentials:
                token = credential.token()
                if not credential.enabled or not token:
                    continue
                for model in provider.models:
                    if model.credentials and credential.id not in model.credentials:
                        continue
                    deployments.append(Deployment(
                        provider_id=provider.id, credential_id=credential.id, token=token,
                        model_id=model.id, model_name=model.name, driver=provider.driver,
                        base_url=provider.base_url, tasks=model.tasks, capabilities=model.capabilities,
                        priority=model.priority, weight=max(0.05, model.weight), temperature=model.temperature,
                        headers=provider.headers, extra=model.extra,
                    ))
        return deployments

    @property
    def configured(self) -> bool:
        return bool(self.deployments)

    def reload(self) -> int:
        """Reload providers.toml and token environment variables without resetting persisted health."""
        self.deployments = self._build_deployments()
        return len(self.deployments)

    async def json(self, *, system: str, user: str, task: str = "general", run_id: str | None = None) -> dict:
        errors: list[str] = []
        tried: set[str] = set()
        for _ in range(self.settings.router_max_attempts):
            candidate = self._pick(task, exclude=tried)
            if candidate is None:
                break
            dep = candidate.deployment
            tried.add(dep.deployment_key)
            started = time.monotonic()
            try:
                text = await self._call(dep, system=system, user=user)
                if _looks_like_refusal(text):
                    raise ProviderFailure("model returned a refusal-style response", kind="refusal")
                try:
                    parsed = extract_first_json_object(text)
                except (ValueError, TypeError) as exc:
                    raise ProviderFailure(f"invalid JSON response: {exc}", kind="json_format") from exc
            except ProviderFailure as exc:
                latency = time.monotonic() - started
                self._record_failure(dep, task, exc, latency=latency, run_id=run_id)
                errors.append(f"{dep.deployment_key}: {exc.kind}: {exc}")
                continue
            latency = time.monotonic() - started
            self._record_success(dep, task, latency=latency, run_id=run_id)
            return parsed
        raise LLMError("No healthy deployment completed the JSON task. " + " | ".join(errors[-4:]))

    async def text(self, *, system: str, user: str, task: str = "general", run_id: str | None = None) -> str:
        errors: list[str] = []
        tried: set[str] = set()
        for _ in range(self.settings.router_max_attempts):
            candidate = self._pick(task, exclude=tried)
            if candidate is None:
                break
            dep = candidate.deployment
            tried.add(dep.deployment_key)
            started = time.monotonic()
            try:
                text = await self._call(dep, system=system, user=user)
                if _looks_like_refusal(text):
                    raise ProviderFailure("model returned a refusal-style response", kind="refusal")
            except ProviderFailure as exc:
                latency = time.monotonic() - started
                self._record_failure(dep, task, exc, latency=latency, run_id=run_id)
                errors.append(f"{dep.deployment_key}: {exc.kind}: {exc}")
                continue
            latency = time.monotonic() - started
            self._record_success(dep, task, latency=latency, run_id=run_id)
            return text
        raise LLMError("No healthy deployment completed the text task. " + " | ".join(errors[-4:]))

    async def _call(self, dep: Deployment, *, system: str, user: str) -> str:
        if dep.driver == "openai_compat":
            return await call_openai_compat(
                dep, system=system, user=user, timeout=self.settings.llm_timeout_seconds,
                temperature=self.settings.llm_temperature,
            )
        if dep.driver == "litellm":
            return await call_litellm(
                dep, system=system, user=user, timeout=self.settings.llm_timeout_seconds,
                temperature=self.settings.llm_temperature,
            )
        raise ProviderFailure(f"Unknown provider driver: {dep.driver}", kind="configuration")

    def _pick(self, task: str, *, exclude: set[str]) -> CandidateView | None:
        now = time.time()
        candidates: list[CandidateView] = []
        for dep in self.deployments:
            if dep.deployment_key in exclude:
                continue
            if "*" not in dep.tasks and task not in dep.tasks:
                continue
            cred = self.storage.router_state("router_credentials", "credential_key", dep.credential_key) or {}
            model = self.storage.router_state("router_deployments", "deployment_key", dep.deployment_key) or {}
            task_state = self.storage.router_task_state(dep.deployment_key, task) or {}
            cred_cd = float(cred.get("cooldown_until") or 0)
            dep_cd = float(model.get("cooldown_until") or 0)
            task_cd = float(task_state.get("cooldown_until") or 0)
            if max(cred_cd, dep_cd, task_cd) > now:
                continue
            model_stats = model if self._observation_fresh(model) else {}
            task_stats = task_state if self._observation_fresh(task_state) else {}
            successes = int(model_stats.get("successes") or 0)
            failures = int(model_stats.get("failures") or 0)
            task_failures = int(task_stats.get("failures") or 0)
            task_successes = int(task_stats.get("successes") or 0)
            failure_ratio = (failures + task_failures) / max(1, successes + failures + task_successes + task_failures)
            latency = float(model_stats.get("latency_ema") or 0)
            # Lower is better. Priority is explicit; health and latency only break/adjust it rather than overriding intent.
            score = (dep.priority + failure_ratio * 35 + min(latency, 20) * 1.5) / dep.weight
            candidates.append(CandidateView(dep, score, cred_cd, dep_cd, task_cd))
        if not candidates:
            return None
        candidates.sort(key=lambda c: (c.score, c.deployment.deployment_key))
        return candidates[0]

    def _record_success(self, dep: Deployment, task: str, *, latency: float, run_id: str | None) -> None:
        self.storage.update_router_credential(
            dep.credential_key, dep.provider_id, dep.credential_id, ok=True, latency=latency
        )
        self.storage.update_router_deployment(
            dep.deployment_key, dep.provider_id, dep.credential_id, dep.model_id, ok=True, latency=latency
        )
        self.storage.update_router_task(dep.deployment_key, task, ok=True)
        self.storage.record_router_attempt(
            run_id=run_id, task=task, provider_id=dep.provider_id, credential_id=dep.credential_id,
            model_id=dep.model_id, deployment_key=dep.deployment_key, ok=True, failure_kind=None,
            status_code=None, latency_seconds=latency, message=None,
        )

    def _record_failure(self, dep: Deployment, task: str, exc: ProviderFailure, *, latency: float, run_id: str | None) -> None:
        now = time.time()
        cred_state = self.storage.router_state("router_credentials", "credential_key", dep.credential_key) or {}
        dep_state = self.storage.router_state("router_deployments", "deployment_key", dep.deployment_key) or {}
        task_state = self.storage.router_task_state(dep.deployment_key, task) or {}

        credential_level = exc.kind in {"auth", "rate_limit"}
        task_level = exc.kind in {"refusal", "json_format"}
        deployment_level = not credential_level and not task_level

        if credential_level:
            count = int(cred_state.get("consecutive_failures") or 0) + 1
            ttl = self._cooldown(exc.kind, count, exc.retry_after)
            self.storage.update_router_credential(
                dep.credential_key, dep.provider_id, dep.credential_id, ok=False,
                cooldown_until=now + ttl, status_code=exc.status_code, error=str(exc), latency=latency,
            )
        # Non-credential failures intentionally do not mutate credential failure counters.
        # This keeps token/auth/quota health independent from model-, network-, task-, or format-level failures.

        if deployment_level:
            count = int(dep_state.get("consecutive_failures") or 0) + 1
            ttl = self._cooldown(exc.kind, count, exc.retry_after)
            self.storage.update_router_deployment(
                dep.deployment_key, dep.provider_id, dep.credential_id, dep.model_id, ok=False,
                cooldown_until=now + ttl, error=str(exc), latency=latency,
            )
        elif not credential_level:
            # Keep deployment aggregate stats without applying a global cooldown.
            self.storage.update_router_deployment(
                dep.deployment_key, dep.provider_id, dep.credential_id, dep.model_id, ok=False,
                cooldown_until=0, error=str(exc), latency=latency,
            )

        if task_level:
            count = int(task_state.get("consecutive_failures") or 0) + 1
            ttl = self._cooldown(exc.kind, count, exc.retry_after)
            self.storage.update_router_task(dep.deployment_key, task, ok=False, cooldown_until=now + ttl, error=str(exc))

        self.storage.record_router_attempt(
            run_id=run_id, task=task, provider_id=dep.provider_id, credential_id=dep.credential_id,
            model_id=dep.model_id, deployment_key=dep.deployment_key, ok=False, failure_kind=exc.kind,
            status_code=exc.status_code, latency_seconds=latency, message=str(exc)[:1000],
        )

    def _observation_fresh(self, state: dict[str, object]) -> bool:
        stamp = state.get("updated_at")
        if not stamp:
            return False
        try:
            age = time.time() - datetime.fromisoformat(str(stamp)).astimezone(timezone.utc).timestamp()
        except (ValueError, TypeError):
            return False
        return age <= self.settings.router_health_ttl_seconds

    @staticmethod
    def _cooldown(kind: str, consecutive: int, retry_after: float | None) -> float:
        if retry_after is not None and retry_after > 0:
            return min(max(retry_after, 1.0), 86_400.0)
        base, cap = {
            "auth": (3600.0, 86_400.0),
            "rate_limit": (30.0, 3600.0),
            "model_or_request": (600.0, 21_600.0),
            "timeout": (10.0, 180.0),
            "network": (10.0, 180.0),
            "upstream": (20.0, 300.0),
            "malformed": (60.0, 900.0),
            "json_format": (30.0, 600.0),
            "refusal": (180.0, 3600.0),
            "configuration": (3600.0, 86_400.0),
        }.get(kind, (30.0, 600.0))
        return min(cap, base * math.pow(2, min(max(consecutive - 1, 0), 6)))

    def status_rows(self, task: str = "general") -> list[dict[str, object]]:
        now = time.time()
        rows: list[dict[str, object]] = []
        for dep in self.deployments:
            cred = self.storage.router_state("router_credentials", "credential_key", dep.credential_key) or {}
            model = self.storage.router_state("router_deployments", "deployment_key", dep.deployment_key) or {}
            task_state = self.storage.router_task_state(dep.deployment_key, task) or {}
            until = max(float(cred.get("cooldown_until") or 0), float(model.get("cooldown_until") or 0), float(task_state.get("cooldown_until") or 0))
            rows.append({
                "provider": dep.provider_id, "credential": dep.credential_id, "model": dep.model_id,
                "model_name": dep.model_name, "driver": dep.driver,
                "tasks": ",".join(sorted(dep.tasks)), "healthy": until <= now,
                "cooldown_seconds": max(0, int(until - now)),
                "successes": int(model.get("successes") or 0), "failures": int(model.get("failures") or 0),
                "latency": round(float(model.get("latency_ema") or 0), 2),
            })
        return rows


def _looks_like_refusal(text: str) -> bool:
    normalized = " ".join(text.lower().split())[:1200]
    return len(normalized) < 1000 and any(marker in normalized for marker in _REFUSAL_MARKERS)
