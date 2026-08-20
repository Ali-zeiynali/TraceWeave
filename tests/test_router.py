from __future__ import annotations

import time
from datetime import UTC
from pathlib import Path

import pytest

from traceweave.config import Settings
from traceweave.models import ResearchSpec
from traceweave.providers.base import LLMError, ProviderFailure
from traceweave.providers.router import ModelRouter
from traceweave.storage import Storage


def _router(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: str) -> ModelRouter:
    path = tmp_path / "providers.toml"
    path.write_text(config, encoding="utf-8")
    monkeypatch.setenv("KEY_A", "secret-a")
    monkeypatch.setenv("KEY_B", "secret-b")
    storage = Storage(tmp_path / "db.sqlite", tmp_path / "data")
    storage.init()
    return ModelRouter(Settings(data_dir=tmp_path / "data", provider_config=path), storage)


@pytest.mark.asyncio
async def test_rate_limit_cools_token_not_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    router = _router(
        tmp_path,
        monkeypatch,
        """
[[providers]]
id="p"
driver="openai_compat"
base_url="https://example.invalid/v1"
[[providers.credentials]]
id="a"
token_env="KEY_A"
[[providers.credentials]]
id="b"
token_env="KEY_B"
[[providers.models]]
id="m"
name="model"
tasks=["planning"]
priority=10
""",
    )

    async def fake_call(dep, *, system, user):
        if dep.credential_id == "a":
            raise ProviderFailure("quota", kind="rate_limit", status_code=429, retry_after=120)
        return '{"objective":"ok","focus":[],"queries":["q"]}'

    monkeypatch.setattr(router, "_call", fake_call)
    data = await router.json(system="s", user="u", task="planning")
    assert data["objective"] == "ok"
    a = router.storage.router_state("router_credentials", "credential_key", "p:a")
    b = router.storage.router_state("router_credentials", "credential_key", "p:b")
    assert a and a["cooldown_until"] > time.time() + 100
    assert b and b["successes"] == 1


@pytest.mark.asyncio
async def test_refusal_is_task_deployment_scoped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    router = _router(
        tmp_path,
        monkeypatch,
        """
[[providers]]
id="p"
driver="openai_compat"
base_url="https://example.invalid/v1"
[[providers.credentials]]
id="a"
token_env="KEY_A"
[[providers.models]]
id="m1"
name="model1"
tasks=["synthesis"]
priority=5
[[providers.models]]
id="m2"
name="model2"
tasks=["synthesis"]
priority=10
""",
    )

    async def fake_call(dep, *, system, user):
        if dep.model_id == "m1":
            return "I cannot assist with that request."
        return "usable answer"

    monkeypatch.setattr(router, "_call", fake_call)
    text = await router.text(system="s", user="u", task="synthesis")
    assert text == "usable answer"
    cred = router.storage.router_state("router_credentials", "credential_key", "p:a")
    task = router.storage.router_task_state("p:a:m1", "synthesis")
    assert cred and float(cred["cooldown_until"] or 0) == 0
    assert int(cred["failures"] or 0) == 0  # refusal must not inflate token/auth failure health
    assert task and task["cooldown_until"] > time.time()


def test_retry_after_http_date_and_reset_seconds():
    from datetime import datetime, timedelta
    from email.utils import format_datetime

    from traceweave.providers.drivers import parse_retry_after

    future = datetime.now(UTC) + timedelta(seconds=90)
    value = parse_retry_after({"Retry-After": format_datetime(future)})
    assert value is not None and 70 <= value <= 95
    assert parse_retry_after({"X-RateLimit-Reset-Tokens": "2m"}) == 120


@pytest.mark.asyncio
async def test_quota_402_cools_only_one_credential(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    router = _router(
        tmp_path,
        monkeypatch,
        """
[[providers]]
id="p"
driver="openai_compat"
base_url="https://example.invalid/v1"
[[providers.credentials]]
id="a"
token_env="KEY_A"
[[providers.credentials]]
id="b"
token_env="KEY_B"
[[providers.models]]
id="m"
name="model"
tasks=["triage"]
priority=10
""",
    )

    async def fake_call(dep, *, system, user):
        if dep.credential_id == "a":
            raise ProviderFailure("credits exhausted", kind="quota", status_code=402)
        return '{"relevance":88}'

    monkeypatch.setattr(router, "_call", fake_call)
    assert (await router.json(system="s", user="u", task="triage"))["relevance"] == 88
    a = router.storage.router_state("router_credentials", "credential_key", "p:a")
    b = router.storage.router_state("router_credentials", "credential_key", "p:b")
    assert a and a["cooldown_until"] > time.time()
    assert b and b["successes"] == 1


@pytest.mark.asyncio
async def test_model_permission_403_does_not_poison_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    router = _router(
        tmp_path,
        monkeypatch,
        """
[[providers]]
id="p"
driver="openai_compat"
base_url="https://example.invalid/v1"
[[providers.credentials]]
id="a"
token_env="KEY_A"
[[providers.models]]
id="m1"
name="model1"
tasks=["planning"]
priority=5
[[providers.models]]
id="m2"
name="model2"
tasks=["planning"]
priority=10
""",
    )

    async def fake_call(dep, *, system, user):
        if dep.model_id == "m1":
            raise ProviderFailure("model forbidden", kind="model_or_request", status_code=403)
        return '{"objective":"ok","focus":[],"queries":["q"]}'

    monkeypatch.setattr(router, "_call", fake_call)
    assert (await router.json(system="s", user="u", task="planning"))["objective"] == "ok"
    cred = router.storage.router_state("router_credentials", "credential_key", "p:a")
    dep = router.storage.router_state("router_deployments", "deployment_key", "p:a:m1")
    assert cred and int(cred["failures"] or 0) == 0 and float(cred["cooldown_until"] or 0) == 0
    assert dep and dep["cooldown_until"] > time.time()


@pytest.mark.asyncio
async def test_remote_vision_requires_opt_in_and_has_separate_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    router = _router(
        tmp_path,
        monkeypatch,
        """
[[providers]]
id="p"
driver="openai_compat"
base_url="https://example.invalid/v1"
[[providers.credentials]]
id="a"
token_env="KEY_A"
[[providers.models]]
id="vision"
name="vision-model"
tasks=["vision"]
capabilities=["text", "json", "vision"]
priority=5
""",
    )
    router.settings.remote_vision_enabled = True
    run_id = router.storage.create_run(
        ResearchSpec(
            topic="Public product photo",
            allow_remote_vision=True,
            max_vision_calls=1,
            max_model_calls=3,
        )
    )

    async def fake_vision(dep, *, system, user, image, media_type):
        del dep, system, user, image, media_type
        return '{"summary":"board","observations":[{"kind":"visible_text","text":"Lantern"}]}'

    monkeypatch.setattr(router, "_call_vision", fake_vision)
    payload = await router.vision_json(
        system="s",
        user="u",
        image=b"image",
        media_type="image/png",
        run_id=run_id,
    )
    assert payload["observations"][0]["text"] == "Lantern"
    with pytest.raises(LLMError, match="Vision-call budget exhausted"):
        await router.vision_json(
            system="s",
            user="u",
            image=b"image",
            media_type="image/png",
            run_id=run_id,
        )


@pytest.mark.asyncio
async def test_model_budget_is_hard_across_fallback_attempts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    router = _router(
        tmp_path,
        monkeypatch,
        """
[[providers]]
id="p"
driver="openai_compat"
base_url="https://example.invalid/v1"
[[providers.credentials]]
id="a"
token_env="KEY_A"
[[providers.credentials]]
id="b"
token_env="KEY_B"
[[providers.models]]
id="m"
name="model"
tasks=["planning"]
priority=5
""",
    )
    run_id = router.storage.create_run(ResearchSpec(topic="Budgeted run", max_model_calls=1))
    called: list[str] = []

    async def always_fails(dep, *, system, user):
        del system, user
        called.append(dep.credential_id)
        raise ProviderFailure("temporary", kind="upstream", status_code=503)

    monkeypatch.setattr(router, "_call", always_fails)
    with pytest.raises(LLMError, match="Model-call budget exhausted"):
        await router.json(system="s", user="u", task="planning", run_id=run_id)
    assert len(called) == 1
    assert router.storage.router_attempt_count(run_id) == 1
