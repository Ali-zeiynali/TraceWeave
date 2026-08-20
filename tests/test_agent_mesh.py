from __future__ import annotations

from pathlib import Path

import pytest

from traceweave.agent import PromptInterpreter
from traceweave.config import Settings
from traceweave.engine import ResearchEngine
from traceweave.models import ResearchSpec, SearchResult, SourceView
from traceweave.providers.presets import providers_from_env
from traceweave.providers.router import ModelRouter
from traceweave.storage import Storage


def test_provider_presets_accept_five_tokens_and_three_cloudflare_accounts(monkeypatch) -> None:
    for idx in range(1, 6):
        suffix = "" if idx == 1 else f"_{idx}"
        monkeypatch.setenv(f"GROQ_API_KEY{suffix}", f"groq-{idx}")
    for idx in range(1, 4):
        suffix = "" if idx == 1 else f"_{idx}"
        monkeypatch.setenv(f"CLOUDFLARE_API_KEY{suffix}", f"cf-{idx}")
        monkeypatch.setenv(f"CLOUDFLARE_ACCOUNT_ID{suffix}", f"account-{idx}")

    providers = {provider.id: provider for provider in providers_from_env()}
    assert [credential.id for credential in providers["groq"].credentials] == [
        "token-1",
        "token-2",
        "token-3",
        "token-4",
        "token-5",
    ]
    cloudflare = providers["cloudflare"].credentials
    assert len(cloudflare) == 3
    assert [credential.base_url for credential in cloudflare] == [
        f"https://api.cloudflare.com/client/v4/accounts/account-{idx}/ai/v1" for idx in range(1, 4)
    ]


@pytest.mark.asyncio
async def test_prompt_interpreter_keeps_explicit_quick_mode_and_extracts_persian_topic() -> None:
    class Provider:
        async def json(self, **kwargs):
            del kwargs
            return {"topic": "Cloudflare Workers AI", "mode": "standard", "language": "en"}

    spec = await PromptInterpreter(Provider()).resolve(
        "یک گزارش کوتاه درباره تغییرات مهم Cloudflare Workers AI در سال 2026 بده"
    )
    assert spec.mode == "quick"
    assert spec.topic == "Cloudflare Workers AI"
    assert spec.language == "en"


def test_task_specific_model_timeouts_are_bounded(tmp_path: Path) -> None:
    config = tmp_path / "providers.toml"
    config.write_text("", encoding="utf-8")
    storage = Storage(tmp_path / "db.sqlite", tmp_path / "data")
    storage.init()
    router = ModelRouter(
        Settings(data_dir=tmp_path / "data", provider_config=config, llm_timeout_seconds=75),
        storage,
    )
    assert router._task_timeout("intent") == 25
    assert router._task_timeout("planning") == 45
    assert router._task_timeout("synthesis") == 75
    assert router._task_attempts("triage") == 3
    assert router._task_attempts("planning") == min(4, router.settings.router_max_attempts)


def test_provider_usage_aggregates_tokens_and_failures(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db.sqlite", tmp_path / "data")
    storage.init()
    common = {
        "run_id": None,
        "task": "planning",
        "provider_id": "provider-a",
        "credential_id": "token-1",
        "model_id": "model-a",
        "deployment_key": "provider-a:token-1:model-a",
        "status_code": None,
        "latency_seconds": 0.5,
        "message": None,
    }
    storage.record_router_attempt(
        **common,
        ok=True,
        failure_kind=None,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
    )
    storage.record_router_attempt(
        **common,
        ok=False,
        failure_kind="network",
    )
    usage = storage.provider_usage()[0]
    assert (usage["requests"], usage["successes"], usage["failures"]) == (2, 1, 1)
    assert usage["total_tokens"] == 15


def test_cached_search_reuses_only_lexically_related_public_results(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db.sqlite", tmp_path / "data")
    storage.init()
    run_id = storage.create_run(ResearchSpec(topic="Cloudflare Workers AI"))
    storage.add_search_result(
        run_id,
        "Cloudflare Workers AI updates",
        1,
        SearchResult(
            url="https://developers.cloudflare.com/workers-ai/",
            title="Cloudflare Workers AI documentation",
            snippet="Workers AI platform updates and models",
            engine="fixture",
        ),
    )
    storage.add_search_result(
        run_id,
        "unrelated",
        1,
        SearchResult(
            url="https://example.com/cooking",
            title="Cooking recipes",
            snippet="Bread and soup",
            engine="fixture",
        ),
    )

    results = storage.cached_search("Cloudflare Workers AI models")
    assert [result.url for result in results] == ["https://developers.cloudflare.com/workers-ai/"]
    assert results[0].engine == "traceweave-cache"


def test_quick_triage_is_bounded_and_domain_diverse() -> None:
    sources = [
        SourceView(
            id=index,
            url=f"https://domain{index // 4}.example/item/{index}",
            canonical_url=f"https://domain{index // 4}.example/item/{index}",
            title=f"Cloudflare Workers AI update {index}",
            domain=f"domain{index // 4}.example",
            snippet="Cloudflare Workers AI models",
            rank=(index % 4) + 1,
            fetched=index % 2 == 0,
        )
        for index in range(20)
    ]
    selected = ResearchEngine._prioritize_sources(
        ResearchSpec(topic="Cloudflare Workers AI", mode="quick"), sources
    )
    assert len(selected) == 8
    assert all(sum(item.domain == source.domain for item in selected) <= 2 for source in selected)
    assert any(source.fetched for source in selected[:2])


def test_page_metadata_date_is_reused_for_later_discovery(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db.sqlite", tmp_path / "data")
    storage.init()
    first_run = storage.create_run(ResearchSpec(topic="Temporal evidence"))
    result = SearchResult(url="https://example.com/change", title="Product change", engine="fixture")
    source_id = storage.add_search_result(first_run, "change", 1, result)
    storage.add_observation(
        first_run,
        kind="page_metadata",
        value_text='{"social":{"article:published_time":"2026-08-07T12:00:00Z"}}',
        source_id=source_id,
    )

    second_run = storage.create_run(ResearchSpec(topic="Temporal evidence follow-up"))
    storage.add_search_result(second_run, "change follow-up", 1, result)
    assert storage.sources_for_run(second_run)[0].published_at == "2026-08-07T12:00:00Z"
