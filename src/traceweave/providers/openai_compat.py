"""Compatibility shim. Stage 2/3 routes OpenAI-compatible endpoints through ModelRouter."""

from traceweave.providers.drivers import call_openai_compat

__all__ = ["call_openai_compat"]
