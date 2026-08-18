from __future__ import annotations

from traceweave.config import Settings
from traceweave.providers.base import LLMProvider
from traceweave.providers.openai_compat import OpenAICompatibleProvider


def build_provider(settings: Settings) -> LLMProvider | None:
    if not settings.llm_configured:
        return None
    return OpenAICompatibleProvider(
        base_url=settings.api_base,
        api_key=settings.api_key,
        model=settings.model,
        timeout=settings.llm_timeout_seconds,
        temperature=settings.llm_temperature,
    )
