"""Offline smoke test: storage + iterative engine using a fake search backend."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from traceweave.config import Settings
from traceweave.engine import ResearchEngine
from traceweave.models import ResearchSpec, SearchResult
from traceweave.planner import Planner
from traceweave.storage import Storage


class FakeSearch:
    name = "smoke"

    async def search(self, query: str, *, limit: int, language: str):
        return [SearchResult(url=f"https://example.com/{len(query)}", title=query, snippet="smoke", engine="smoke")]


class Engine(ResearchEngine):
    async def _fetch_source(self, run_id: str, source_id: int, url: str) -> None:
        return None


async def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        settings = Settings(data_dir=root / "data", archives_enabled=False, academic_enabled=False, github_enabled=False, entity_graph_enabled=False, frontier_enabled=False)
        settings.ensure_dirs()
        storage = Storage(settings.db_path, settings.data_dir)
        storage.init()
        engine = Engine(
            settings=settings,
            storage=storage,
            search=FakeSearch(),
            planner=Planner(None),
            provider=None,
        )
        run_id = await engine.start(ResearchSpec(topic="TraceWeave smoke test", max_rounds=2, fetch_top_per_query=0))
        row = storage.get_run(run_id)
        assert row and row["status"] == "completed" and row["current_round"] == 2
        assert storage.sources_for_run(run_id)
        print(f"SMOKE OK: {run_id}")


if __name__ == "__main__":
    asyncio.run(main())
