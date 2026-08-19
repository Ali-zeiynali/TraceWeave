from __future__ import annotations

import json
from importlib.resources import files

from traceweave.models import ExtractedClaim, ResearchSpec, SourceView, TriageResult
from traceweave.providers.base import LLMError, LLMProvider
from traceweave.storage import Storage
from traceweave.skills import SkillRegistry
from traceweave.utils import lexical_overlap


def _prompt(name: str) -> str:
    return files("traceweave.prompts").joinpath(name).read_text(encoding="utf-8")


class EvidenceAnalyzer:
    def __init__(self, storage: Storage, provider: LLMProvider | None):
        self.storage = storage
        self.provider = provider
        self.skills = SkillRegistry()

    async def triage(self, run_id: str, spec: ResearchSpec, source: SourceView, prior: list[SourceView]) -> TriageResult:
        if self.provider is None:
            return self._heuristic_triage(spec, source)
        payload = {
            "research": {"topic": spec.topic, "angle": spec.angle, "mode": spec.mode},
            "source": {
                "id": source.id, "url": source.url, "title": source.title, "domain": source.domain,
                "category": source.category, "published_at": source.published_at,
                "snippet": source.snippet[:1200], "content": source.text_excerpt[:9000],
            },
            "prior_source_capsules": [
                {"id": x.id, "title": x.title, "domain": x.domain, "snippet": x.snippet[:350]}
                for x in prior[:12] if x.id != source.id
            ],
        }
        try:
            data = await self.provider.json(
                system=_prompt("triage.txt") + "\n\n" + self.skills.for_task("triage"), user=json.dumps(payload, ensure_ascii=False),
                task="triage", run_id=run_id,
            )
            return TriageResult.model_validate(data)
        except (LLMError, ValueError):
            return self._heuristic_triage(spec, source)

    async def extract_claims(self, run_id: str, spec: ResearchSpec, source: SourceView) -> list[ExtractedClaim]:
        if self.provider is None or not source.text_excerpt:
            return []
        payload = {
            "research_goal": spec.topic,
            "angle": spec.angle,
            "source_id": source.id,
            "source_url": source.url,
            "SOURCE": source.text_excerpt[:16000],
        }
        try:
            data = await self.provider.json(
                system=_prompt("claims.txt") + "\n\n" + self.skills.for_task("claim_extraction"), user=json.dumps(payload, ensure_ascii=False),
                task="claim_extraction", run_id=run_id,
            )
        except (LLMError, ValueError):
            return []
        out: list[ExtractedClaim] = []
        for item in data.get("claims", [])[:10]:
            try:
                claim = ExtractedClaim.model_validate(item)
            except ValueError:
                continue
            # Grounding gate: only persist evidence quotes that literally occur in stored source text.
            if claim.evidence_quote not in source.text_excerpt:
                continue
            out.append(claim)
        return out

    @staticmethod
    def _heuristic_triage(spec: ResearchSpec, source: SourceView) -> TriageResult:
        haystack = f"{source.title}\n{source.snippet}\n{source.text_excerpt[:4000]}"
        rel = lexical_overlap(f"{spec.topic} {spec.angle}", haystack)
        relevance = min(100.0, 25.0 + rel * 150.0)
        path = source.url.casefold()
        authority = 45.0
        if any(x in path for x in ("/report", ".pdf", "/press", "/newsroom", "/investor", "/about")):
            authority += 12.0
        if source.category == "news":
            authority += 5.0
        importance = min(100.0, relevance * 0.85 + (10.0 if source.published_at else 0.0))
        novelty = 60.0 if source.fetched else 45.0
        return TriageResult(
            relevance=round(relevance, 1), importance=round(importance, 1), novelty=novelty,
            authority=min(100.0, authority), rationale="Deterministic lexical/source heuristic",
            topics=[], leads=[],
        )
