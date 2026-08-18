from __future__ import annotations

from pathlib import Path

import pytest

from traceweave.config import Settings
from traceweave.engine import ResearchEngine
from traceweave.models import Plan, ResearchSpec, SearchResult
from traceweave.planner import Planner
from traceweave.storage import Storage


class FakeSearch:
    name = "fake"

    async def search(self, query: str, *, limit: int, language: str):
        del language
        return [
            SearchResult(
                url=f"https://example.com/{abs(hash(query)) % 10000}",
                title=f"Result for {query}",
                snippet="fixture evidence",
                engine="fake",
                category="web",
            )
        ][:limit]


class NoFetchEngine(ResearchEngine):
    async def _fetch_source(self, run_id: str, source_id: int, url: str) -> None:
        await self._emit(run_id, "source.fetch_skipped", "test fixture", source_id=source_id, url=url)


@pytest.mark.asyncio
async def test_plan_search_replan_and_resumeable_state(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        search_backend="ddgs",
    )
    settings.ensure_dirs()
    storage = Storage(settings.db_path, settings.data_dir)
    storage.init()
    planner = Planner(None)
    engine = NoFetchEngine(
        settings=settings,
        storage=storage,
        search=FakeSearch(),
        planner=planner,
        provider=None,
    )
    run_id = await engine.start(
        ResearchSpec(topic="Acme Research", mode="standard", max_rounds=2, fetch_top_per_query=0)
    )
    run = storage.get_run(run_id)
    assert run is not None
    assert run["status"] == "completed"
    assert run["current_round"] == 2
    assert len(storage.completed_queries(run_id)) >= 2
    assert len(storage.sources_for_run(run_id)) >= 2
    assert storage.get_plan(run_id, 1) is not None
    assert storage.get_plan(run_id, 2) is not None
