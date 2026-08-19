from __future__ import annotations

from traceweave.config import Settings
from traceweave.providers.router import ModelRouter
from traceweave.storage import Storage


def build_provider(settings: Settings, storage: Storage) -> ModelRouter | None:
    router = ModelRouter(settings, storage)
    return router if router.configured else None
