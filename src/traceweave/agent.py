from __future__ import annotations

import json
import re
from importlib.resources import files

from traceweave.models import ResearchSpec
from traceweave.providers.base import LLMError, LLMProvider


class PromptInterpreter:
    """Turn one natural-language request into a bounded durable investigation spec."""

    def __init__(self, provider: LLMProvider | None):
        self.provider = provider

    async def resolve(self, prompt: str, *, defaults: ResearchSpec | None = None) -> ResearchSpec:
        base = defaults or self.heuristic(prompt)
        if self.provider is None:
            return base
        system = files("traceweave.prompts").joinpath("intent.txt").read_text(encoding="utf-8")
        try:
            data = await self.provider.json(
                system=system,
                user=json.dumps(
                    {
                        "request": prompt,
                        "defaults": base.model_dump(),
                        "policy": {
                            "public_data_only": True,
                            "exclude_minors": True,
                            "no_access_control_bypass": True,
                        },
                    },
                    ensure_ascii=False,
                ),
                task="intent",
            )
            allowed = {
                "topic",
                "angle",
                "mode",
                "language",
                "deadline_minutes",
                "allow_remote_vision",
                "max_vision_calls",
            }
            merged = base.model_dump()
            merged.update({key: value for key, value in data.items() if key in allowed and value is not None})
            if base.mode != "standard":
                merged["mode"] = base.mode
            # A model cannot silently weaken operator-configured safety/cost limits.
            merged["allow_remote_vision"] = bool(base.allow_remote_vision)
            merged["max_vision_calls"] = base.max_vision_calls
            return ResearchSpec.model_validate(merged)
        except (LLMError, ValueError, TypeError):
            return base

    @staticmethod
    def heuristic(prompt: str) -> ResearchSpec:
        text = " ".join(prompt.split())
        low = text.casefold()
        if any(x in low for x in ("تا صبح", "شب تا", "overnight", "all night", "تا فردا")):
            mode = "overnight"
        elif any(x in low for x in ("کوتاه", "مختصر", "سریع", "quick", "brief", "short report")):
            mode = "quick"
        elif any(x in low for x in ("عمیق", "جامع", "کامل کامل", "deep", "comprehensive", "exhaustive")):
            mode = "deep"
        else:
            mode = "standard"
        if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", text):
            language = "ja"
        elif re.search(r"[\u0600-\u06ff]", text):
            language = "fa"
        else:
            language = "all"
        angle = ""
        for marker in ("با تمرکز بر", "از زاویه", "focus on", "with emphasis on"):
            if marker in low:
                angle = text[low.index(marker) + len(marker) :].strip(" :،")[:500]
                break
        topic = text
        patterns = (
            r"(?:درباره|در مورد)\s+(.+?)(?:\s+(?:بده|تهیه کن|بنویس|تحقیق کن)(?:\s|$))",
            r"(?:research|investigate|report on|tell me about)\s+(.+?)(?:\s+(?:and|with|using)\s+|$)",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match and len(match.group(1).split()) >= 2:
                topic = match.group(1).strip(" :،")
                break
        if topic != text and not angle:
            angle = f"User request: {text}"[:500]
        return ResearchSpec(topic=topic, angle=angle, mode=mode, language=language)
