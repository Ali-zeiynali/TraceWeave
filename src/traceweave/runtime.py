from __future__ import annotations

from dataclasses import dataclass

from traceweave.config import Settings
from traceweave.engine import ProgressCallback, ResearchEngine
from traceweave.planner import Planner
from traceweave.providers.factory import build_provider
from traceweave.providers.router import ModelRouter
from traceweave.search.factory import build_search
from traceweave.storage import Storage


@dataclass(slots=True)
class Runtime:
    settings: Settings
    storage: Storage
    engine: ResearchEngine
    router: ModelRouter | None


def build_runtime(callback: ProgressCallback | None = None, settings: Settings | None = None) -> Runtime:
    settings = settings or Settings()
    settings.ensure_dirs()
    storage = Storage(settings.db_path, settings.data_dir)
    storage.init()
    provider = build_provider(settings, storage)
    engine = ResearchEngine(
        settings=settings, storage=storage, search=build_search(settings), planner=Planner(provider),
        provider=provider, callback=callback,
    )
    return Runtime(settings=settings, storage=storage, engine=engine, router=provider)
