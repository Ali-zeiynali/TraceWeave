from __future__ import annotations

import time
from pathlib import Path

import pytest

from traceweave.config import Settings
from traceweave.providers.base import ProviderFailure
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
    router = _router(tmp_path, monkeypatch, '''
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
''')

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
    router = _router(tmp_path, monkeypatch, '''
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
''')

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
