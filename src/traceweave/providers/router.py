from __future__ import annotations

import asyncio
import contextvars
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from traceweave.config import Settings
from traceweave.providers.base import LLMError, ProviderFailure
from traceweave.providers.catalog import ModelCatalog
from traceweave.providers.config import load_provider_config
from traceweave.providers.drivers import (
    Deployment,
    ProviderResponse,
    call_litellm,
    call_litellm_vision,
    call_openai_compat,
    call_openai_compat_vision,
)
from traceweave.providers.presets import PRESETS, _token_envs, has_env_credentials
from traceweave.storage import Storage
from traceweave.utils import extract_first_json_object

_REFUSAL_MARKERS = (
    "i can't assist with",
    "i cannot assist with",
    "i can't help with",
    "i cannot help with",
    "i'm unable to assist",
    "i am unable to assist",
    "cannot comply",
    "can't comply",
    "抱歉，我不能",
    "无法回答",
    "不能回答",
    "无法提供",
    "متأسفم، نمی‌توانم",
    "متاسفم، نمی توانم",
    "نمی‌توانم در این مورد کمک",
    "نمی توانم در این مورد کمک",
    "لا أستطيع المساعدة",
    "لا يمكنني المساعدة",
    "申し訳ありませんが、お手伝いできません",
    "i must decline",
    "i have to decline",
    "outside my capabilities",
    "not able to fulfill",
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
        self.catalog = ModelCatalog(
            settings.data_dir / "catalog" / "models.json", settings.provider_catalog_ttl_seconds
        )
        self.deployments = self._build_deployments()
        self._catalog_lock = asyncio.Lock()
        self._catalog_failures: dict[str, int] = {}
        self._catalog_retry_until: dict[str, float] = {}
        self._provider_failures: dict[str, int] = {}
        self._provider_retry_until: dict[str, float] = {}
        self._task_context: contextvars.ContextVar[str] = contextvars.ContextVar(
            "traceweave_router_task", default="general"
        )
        self._preferred_deployment: str | None = None
        self._inflight: dict[str, int] = {}

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
                    deployments.append(
                        Deployment(
                            provider_id=provider.id,
                            credential_id=credential.id,
                            token=token,
                            model_id=model.id,
                            model_name=model.name,
                            driver=provider.driver,
                            base_url=credential.base_url or provider.base_url,
                            tasks=model.tasks,
                            capabilities=model.capabilities,
                            priority=model.priority,
                            weight=max(0.05, model.weight),
                            temperature=model.temperature,
                            headers=provider.headers,
                            extra=model.extra,
                        )
                    )
        return deployments

    @property
    def configured(self) -> bool:
        return bool(self.deployments) or has_env_credentials()

    def reload(self) -> int:
        """Reload providers.toml and token environment variables without resetting persisted health."""
        self.deployments = self._build_deployments()
        if self._preferred_deployment and not any(
            dep.deployment_key == self._preferred_deployment for dep in self.deployments
        ):
            self._preferred_deployment = None
        return len(self.deployments)

    async def json(self, *, system: str, user: str, task: str = "general", run_id: str | None = None) -> dict:
        self._check_run_budget(run_id, task=task)
        await self._ensure_for_call(run_id)
        errors: list[str] = []
        tried: set[str] = set()
        for _ in range(self._task_attempts(task)):
            self._check_run_budget(run_id, task=task)
            candidate = self._pick(task, exclude=tried)
            if candidate is None:
                break
            dep = candidate.deployment
            tried.add(dep.deployment_key)
            started = time.monotonic()
            self._acquire_route(dep)
            try:
                task_token = self._task_context.set(task)
                try:
                    response = _as_response(await self._call(dep, system=system, user=user))
                finally:
                    self._task_context.reset(task_token)
                text = response.text
                if _looks_like_refusal(text):
                    raise ProviderFailure("model returned a refusal-style response", kind="refusal")
                try:
                    parsed = extract_first_json_object(text)
                except (ValueError, TypeError) as exc:
                    raise ProviderFailure(f"invalid JSON response: {exc}", kind="json_format") from exc
                if not isinstance(parsed, dict) or not parsed:
                    raise ProviderFailure(
                        "model returned an empty or non-object task result", kind="task_evasion"
                    )
            except ProviderFailure as exc:
                latency = time.monotonic() - started
                self._record_failure(dep, task, exc, latency=latency, run_id=run_id)
                errors.append(f"{dep.deployment_key}: {exc.kind}: {exc}")
                continue
            finally:
                self._release_route(dep)
            latency = time.monotonic() - started
            self._record_success(dep, task, latency=latency, run_id=run_id, response=response)
            return parsed
        raise LLMError("No healthy deployment completed the JSON task. " + " | ".join(errors[-4:]))

    async def text(self, *, system: str, user: str, task: str = "general", run_id: str | None = None) -> str:
        self._check_run_budget(run_id, task=task)
        await self._ensure_for_call(run_id)
        errors: list[str] = []
        tried: set[str] = set()
        for _ in range(self._task_attempts(task)):
            self._check_run_budget(run_id, task=task)
            candidate = self._pick(task, exclude=tried)
            if candidate is None:
                break
            dep = candidate.deployment
            tried.add(dep.deployment_key)
            started = time.monotonic()
            self._acquire_route(dep)
            try:
                task_token = self._task_context.set(task)
                try:
                    response = _as_response(await self._call(dep, system=system, user=user))
                finally:
                    self._task_context.reset(task_token)
                text = response.text
                if _looks_like_refusal(text):
                    raise ProviderFailure("model returned a refusal-style response", kind="refusal")
                if len(text.strip()) < 8:
                    raise ProviderFailure(
                        "model returned an implausibly short task result", kind="task_evasion"
                    )
            except ProviderFailure as exc:
                latency = time.monotonic() - started
                self._record_failure(dep, task, exc, latency=latency, run_id=run_id)
                errors.append(f"{dep.deployment_key}: {exc.kind}: {exc}")
                continue
            finally:
                self._release_route(dep)
            latency = time.monotonic() - started
            self._record_success(dep, task, latency=latency, run_id=run_id, response=response)
            return text
        raise LLMError("No healthy deployment completed the text task. " + " | ".join(errors[-4:]))

    async def vision_json(
        self,
        *,
        system: str,
        user: str,
        image: bytes,
        media_type: str,
        run_id: str,
    ) -> dict:
        self._check_run_budget(run_id, vision=True)
        await self._ensure_for_call(run_id)
        errors: list[str] = []
        tried: set[str] = set()
        for _ in range(self.settings.router_max_attempts):
            self._check_run_budget(run_id, vision=True)
            candidate = self._pick("vision", exclude=tried, required_capabilities={"vision"})
            if candidate is None:
                break
            dep = candidate.deployment
            tried.add(dep.deployment_key)
            started = time.monotonic()
            try:
                response = _as_response(
                    await self._call_vision(
                        dep,
                        system=system,
                        user=user,
                        image=image,
                        media_type=media_type,
                    )
                )
                text = response.text
                if _looks_like_refusal(text):
                    raise ProviderFailure("model returned a refusal-style response", kind="refusal")
                parsed = extract_first_json_object(text)
                if not isinstance(parsed, dict) or not isinstance(parsed.get("observations", []), list):
                    raise ProviderFailure(
                        "vision result does not match the observation contract", kind="task_evasion"
                    )
            except (ValueError, TypeError) as exc:
                failure = ProviderFailure(f"invalid vision JSON response: {exc}", kind="json_format")
                latency = time.monotonic() - started
                self._record_failure(dep, "vision", failure, latency=latency, run_id=run_id)
                errors.append(f"{dep.deployment_key}: {failure.kind}: {failure}")
                continue
            except ProviderFailure as exc:
                latency = time.monotonic() - started
                self._record_failure(dep, "vision", exc, latency=latency, run_id=run_id)
                errors.append(f"{dep.deployment_key}: {exc.kind}: {exc}")
                continue
            latency = time.monotonic() - started
            self._record_success(dep, "vision", latency=latency, run_id=run_id, response=response)
            return parsed
        raise LLMError("No healthy vision deployment completed the task. " + " | ".join(errors[-4:]))

    async def ensure_catalogs(self, *, run_id: str | None = None, force: bool = False) -> dict[str, str]:
        """Refresh dynamic model catalogs per credential when their cache TTL expires.

        A failing /models endpoint is isolated to that provider+credential and receives its own
        exponential retry window. Concurrent research tasks share one refresh lock so they do not
        stampede unstable router endpoints. Token values are never persisted.
        """
        if not self.settings.provider_catalog_auto_sync and not force:
            return {}
        import os

        async with self._catalog_lock:
            results: dict[str, str] = {}
            changed = False
            now = time.time()
            for pid, preset in PRESETS.items():
                if not preset.dynamic_catalog:
                    continue
                token_specs = list(_token_envs(preset.env_prefix))
                if not token_specs:
                    continue
                base_template = os.getenv(f"{preset.env_prefix}_BASE_URL", "").strip() or preset.base_url
                for credential_id, token_env in token_specs:
                    key = f"{pid}:{credential_id}"
                    if not force:
                        if not self.catalog.stale(pid, credential_id):
                            continue
                        if self._catalog_retry_until.get(key, 0) > now:
                            continue
                    token = os.getenv(token_env, "").strip()
                    base = base_template
                    if "{account_id}" in base:
                        slot = credential_id.rsplit("-", 1)[-1]
                        account_env = (
                            f"{preset.env_prefix}_ACCOUNT_ID"
                            if slot == "1"
                            else f"{preset.env_prefix}_ACCOUNT_ID_{slot}"
                        )
                        account_id = os.getenv(account_env, "").strip()
                        if not account_id:
                            continue
                        base = base.replace("{account_id}", account_id)
                    try:
                        rows = await self.catalog.sync_provider(
                            pid,
                            credential_id,
                            token=token,
                            base_url=base,
                            timeout=min(25.0, self.settings.llm_timeout_seconds),
                        )
                        results[key] = f"ok:{len(rows)}"
                        self._catalog_failures.pop(key, None)
                        self._catalog_retry_until.pop(key, None)
                        changed = True
                    except Exception as exc:
                        failures = self._catalog_failures.get(key, 0) + 1
                        self._catalog_failures[key] = failures
                        retry = min(1800.0, 30.0 * (2 ** min(failures - 1, 6)))
                        self._catalog_retry_until[key] = time.time() + retry
                        results[key] = f"error:{type(exc).__name__}:retry={int(retry)}s"
                        self.storage.event(
                            run_id,
                            "provider.catalog_failed",
                            f"Model catalog refresh failed for {pid}/{credential_id}; retry in {int(retry)}s",
                            {
                                "provider": pid,
                                "credential": credential_id,
                                "error": str(exc)[:500],
                                "retry_seconds": retry,
                            },
                        )
            if changed:
                self.deployments = self._build_deployments()
            return results

    async def _ensure_for_call(self, run_id: str | None) -> None:
        """Never put best-effort catalog discovery on the latency path of a known route."""
        if self.deployments:
            return
        await self.ensure_catalogs(run_id=run_id, force=False)

    def primary_route(self, task: str = "planning") -> dict[str, str] | None:
        candidate = self._pick(task, exclude=set())
        if candidate is None:
            return None
        dep = candidate.deployment
        return {
            "provider": dep.provider_id,
            "credential": dep.credential_id,
            "model": dep.model_name,
            "tier": str(dep.extra.get("tier", "")),
            "deployment_key": dep.deployment_key,
            "preferred": str(dep.deployment_key == self._preferred_deployment).lower(),
        }

    def _task_timeout(self, task: str) -> float:
        """Keep cheap routing tasks responsive while allowing synthesis more time."""
        configured = self.settings.llm_timeout_seconds
        if task in {"intent", "triage", "claim", "entity", "claim_extraction", "entity_extraction"}:
            return min(25.0, configured)
        if task in {"planning", "replanning", "verification"}:
            return min(45.0, configured)
        return configured

    def _task_attempts(self, task: str) -> int:
        configured = self.settings.router_max_attempts
        if task == "intent":
            return min(4, configured)
        if task in {"planning", "replanning", "verification"}:
            return min(4, configured)
        if task in {"triage", "claim", "entity", "claim_extraction", "entity_extraction"}:
            return min(3, configured)
        return configured

    async def _call(self, dep: Deployment, *, system: str, user: str) -> ProviderResponse:
        timeout = self._task_timeout(self._task_context.get())
        if dep.driver == "openai_compat":
            return await call_openai_compat(
                dep,
                system=system,
                user=user,
                timeout=timeout,
                temperature=self.settings.llm_temperature,
            )
        if dep.driver == "litellm":
            return await call_litellm(
                dep,
                system=system,
                user=user,
                timeout=timeout,
                temperature=self.settings.llm_temperature,
            )
        raise ProviderFailure(f"Unknown provider driver: {dep.driver}", kind="configuration")

    async def _call_vision(
        self,
        dep: Deployment,
        *,
        system: str,
        user: str,
        image: bytes,
        media_type: str,
    ) -> str:
        caller = call_openai_compat_vision if dep.driver == "openai_compat" else call_litellm_vision
        if dep.driver not in {"openai_compat", "litellm"}:
            raise ProviderFailure(f"Unknown provider driver: {dep.driver}", kind="configuration")
        return await caller(
            dep,
            system=system,
            user=user,
            image=image,
            media_type=media_type,
            timeout=self.settings.llm_timeout_seconds,
            temperature=self.settings.llm_temperature,
        )

    def _pick(
        self,
        task: str,
        *,
        exclude: set[str],
        required_capabilities: set[str] | None = None,
    ) -> CandidateView | None:
        now = time.time()
        candidates: list[CandidateView] = []
        for dep in self.deployments:
            if dep.deployment_key in exclude:
                continue
            if self._provider_retry_until.get(dep.provider_id, 0) > now:
                continue
            if "*" not in dep.tasks and task not in dep.tasks:
                continue
            if required_capabilities and not required_capabilities <= dep.capabilities:
                continue
            # Explicitly paid routes are blocked. Unknown custom endpoints remain usable so
            # self-hosted/community routers are not accidentally rejected.
            if self.settings.zero_cost_only and dep.extra.get("free") is False:
                continue
            cred = self.storage.router_state("router_credentials", "credential_key", dep.credential_key) or {}
            model = (
                self.storage.router_state("router_deployments", "deployment_key", dep.deployment_key) or {}
            )
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
            failure_ratio = (failures + task_failures) / max(
                1, successes + failures + task_successes + task_failures
            )
            latency = float(model_stats.get("latency_ema") or 0)
            # Lower is better. Priority is explicit; health and latency only break/adjust it rather than overriding intent.
            preference = -10_000 if dep.deployment_key == self._preferred_deployment else 0
            # Concurrent triage/claim calls must not stampede one slow or failing route.
            # A preferred route wins the first lease, then healthy fallbacks can make progress.
            inflight_penalty = self._inflight.get(dep.deployment_key, 0) * 20_000
            score = (
                dep.priority + failure_ratio * 35 + min(latency, 20) * 1.5 + preference + inflight_penalty
            ) / dep.weight
            candidates.append(CandidateView(dep, score, cred_cd, dep_cd, task_cd))
        if not candidates:
            return None
        candidates.sort(key=lambda c: (c.score, c.deployment.deployment_key))
        return candidates[0]

    def _record_success(
        self,
        dep: Deployment,
        task: str,
        *,
        latency: float,
        run_id: str | None,
        response: ProviderResponse,
    ) -> None:
        self.storage.update_router_credential(
            dep.credential_key, dep.provider_id, dep.credential_id, ok=True, latency=latency
        )
        self._provider_failures.pop(dep.provider_id, None)
        self._provider_retry_until.pop(dep.provider_id, None)
        self.storage.update_router_deployment(
            dep.deployment_key, dep.provider_id, dep.credential_id, dep.model_id, ok=True, latency=latency
        )
        self.storage.update_router_task(dep.deployment_key, task, ok=True)
        self.storage.record_router_attempt(
            run_id=run_id,
            task=task,
            provider_id=dep.provider_id,
            credential_id=dep.credential_id,
            model_id=dep.model_id,
            deployment_key=dep.deployment_key,
            ok=True,
            failure_kind=None,
            status_code=None,
            latency_seconds=latency,
            message=None,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.total_tokens,
            response_id=response.response_id,
        )

    def _record_failure(
        self, dep: Deployment, task: str, exc: ProviderFailure, *, latency: float, run_id: str | None
    ) -> None:
        now = time.time()
        cred_state = (
            self.storage.router_state("router_credentials", "credential_key", dep.credential_key) or {}
        )
        dep_state = (
            self.storage.router_state("router_deployments", "deployment_key", dep.deployment_key) or {}
        )
        task_state = self.storage.router_task_state(dep.deployment_key, task) or {}

        credential_level = exc.kind in {"auth", "quota", "rate_limit"}
        task_level = exc.kind in {"refusal", "json_format", "task_evasion"}
        deployment_level = not credential_level and not task_level
        if exc.kind == "network":
            failures = self._provider_failures.get(dep.provider_id, 0) + 1
            self._provider_failures[dep.provider_id] = failures
            self._provider_retry_until[dep.provider_id] = now + min(900.0, 30.0 * (2 ** min(failures - 1, 5)))

        if credential_level:
            count = int(cred_state.get("consecutive_failures") or 0) + 1
            ttl = self._cooldown(exc.kind, count, exc.retry_after)
            self.storage.update_router_credential(
                dep.credential_key,
                dep.provider_id,
                dep.credential_id,
                ok=False,
                cooldown_until=now + ttl,
                status_code=exc.status_code,
                error=str(exc),
                latency=latency,
            )
        # Non-credential failures intentionally do not mutate credential failure counters.
        # This keeps token/auth/quota health independent from model-, network-, task-, or format-level failures.

        if deployment_level:
            count = int(dep_state.get("consecutive_failures") or 0) + 1
            ttl = self._cooldown(exc.kind, count, exc.retry_after)
            self.storage.update_router_deployment(
                dep.deployment_key,
                dep.provider_id,
                dep.credential_id,
                dep.model_id,
                ok=False,
                cooldown_until=now + ttl,
                error=str(exc),
                latency=latency,
            )
        elif not credential_level:
            # Keep deployment aggregate stats without applying a global cooldown.
            self.storage.update_router_deployment(
                dep.deployment_key,
                dep.provider_id,
                dep.credential_id,
                dep.model_id,
                ok=False,
                cooldown_until=0,
                error=str(exc),
                latency=latency,
            )

        if task_level:
            count = int(task_state.get("consecutive_failures") or 0) + 1
            ttl = self._cooldown(exc.kind, count, exc.retry_after)
            self.storage.update_router_task(
                dep.deployment_key, task, ok=False, cooldown_until=now + ttl, error=str(exc)
            )

        self.storage.record_router_attempt(
            run_id=run_id,
            task=task,
            provider_id=dep.provider_id,
            credential_id=dep.credential_id,
            model_id=dep.model_id,
            deployment_key=dep.deployment_key,
            ok=False,
            failure_kind=exc.kind,
            status_code=exc.status_code,
            latency_seconds=latency,
            message=str(exc)[:1000],
        )

    def _observation_fresh(self, state: dict[str, object]) -> bool:
        stamp = state.get("updated_at")
        if not stamp:
            return False
        try:
            age = time.time() - datetime.fromisoformat(str(stamp)).astimezone(UTC).timestamp()
        except (ValueError, TypeError):
            return False
        return age <= self.settings.router_health_ttl_seconds

    @staticmethod
    def _cooldown(kind: str, consecutive: int, retry_after: float | None) -> float:
        if retry_after is not None and retry_after > 0:
            return min(max(retry_after, 1.0), 86_400.0)
        base, cap = {
            "auth": (3600.0, 86_400.0),
            "quota": (300.0, 21_600.0),
            "rate_limit": (30.0, 3600.0),
            "model_or_request": (600.0, 21_600.0),
            "timeout": (10.0, 180.0),
            "network": (10.0, 180.0),
            "upstream": (20.0, 300.0),
            "malformed": (60.0, 900.0),
            "json_format": (30.0, 600.0),
            "refusal": (180.0, 3600.0),
            "task_evasion": (120.0, 1800.0),
            "configuration": (3600.0, 86_400.0),
        }.get(kind, (30.0, 600.0))
        return min(cap, base * math.pow(2, min(max(consecutive - 1, 0), 6)))

    def status_rows(self, task: str = "general") -> list[dict[str, object]]:
        now = time.time()
        rows: list[dict[str, object]] = []
        for dep in self.deployments:
            cred = self.storage.router_state("router_credentials", "credential_key", dep.credential_key) or {}
            model = (
                self.storage.router_state("router_deployments", "deployment_key", dep.deployment_key) or {}
            )
            task_state = self.storage.router_task_state(dep.deployment_key, task) or {}
            until = max(
                float(cred.get("cooldown_until") or 0),
                float(model.get("cooldown_until") or 0),
                float(task_state.get("cooldown_until") or 0),
            )
            rows.append(
                {
                    "provider": dep.provider_id,
                    "credential": dep.credential_id,
                    "model": dep.model_id,
                    "model_name": dep.model_name,
                    "deployment_key": dep.deployment_key,
                    "preferred": dep.deployment_key == self._preferred_deployment,
                    "driver": dep.driver,
                    "tasks": ",".join(sorted(dep.tasks)),
                    "healthy": until <= now,
                    "cooldown_seconds": max(0, int(until - now)),
                    "successes": int(model.get("successes") or 0),
                    "failures": int(model.get("failures") or 0),
                    "latency": round(float(model.get("latency_ema") or 0), 2),
                }
            )
        return rows

    @property
    def preferred_deployment(self) -> str | None:
        return self._preferred_deployment

    def prefer(self, deployment_key: str | None) -> bool:
        """Prefer one route while retaining health-based fallback to the remaining mesh."""
        if not deployment_key or deployment_key.casefold() == "auto":
            self._preferred_deployment = None
            return True
        if not any(dep.deployment_key == deployment_key for dep in self.deployments):
            return False
        self._preferred_deployment = deployment_key
        return True

    def _acquire_route(self, dep: Deployment) -> None:
        self._inflight[dep.deployment_key] = self._inflight.get(dep.deployment_key, 0) + 1

    def _release_route(self, dep: Deployment) -> None:
        remaining = self._inflight.get(dep.deployment_key, 1) - 1
        if remaining > 0:
            self._inflight[dep.deployment_key] = remaining
        else:
            self._inflight.pop(dep.deployment_key, None)

    def _check_run_budget(
        self,
        run_id: str | None,
        *,
        task: str = "general",
        vision: bool = False,
    ) -> None:
        if not run_id:
            return
        run = self.storage.get_run(run_id)
        if not run:
            return
        maximum = int(run.get("max_model_calls") or 0)
        used = self.storage.router_attempt_count(run_id)
        if maximum >= 0 and used >= maximum:
            raise LLMError(f"Model-call budget exhausted ({maximum})")
        # Keep bounded runs useful under provider outages. Early planning/triage may use most
        # of the budget, but cannot consume the attempts reserved for grounded claims and a
        # final synthesis. Very small explicit budgets retain the original hard-cap semantics.
        if maximum >= 8 and not vision:
            final_reserve = min(10, max(2, maximum // 4))
            reserve = (
                0
                if task == "synthesis"
                else 2
                if task in {"claim_extraction", "verification"}
                else final_reserve
            )
            if used >= maximum - reserve:
                raise LLMError(
                    f"Model-call stage budget exhausted for {task}; {reserve} of {maximum} attempts "
                    "are reserved for grounded claims/final synthesis"
                )
        if vision:
            if not self.settings.remote_vision_enabled or not bool(run.get("allow_remote_vision")):
                raise LLMError("Remote vision is disabled by policy or for this run")
            vision_maximum = int(run.get("max_vision_calls") or 0)
            if self.storage.router_attempt_count(run_id, task="vision") >= vision_maximum:
                raise LLMError(f"Vision-call budget exhausted ({vision_maximum})")


def _looks_like_refusal(text: str) -> bool:
    normalized = " ".join(text.lower().split())[:1200]
    return any(marker in normalized for marker in _REFUSAL_MARKERS)


def _as_response(value: ProviderResponse | str) -> ProviderResponse:
    return value if isinstance(value, ProviderResponse) else ProviderResponse(text=str(value))
