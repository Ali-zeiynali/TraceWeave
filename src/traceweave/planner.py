from __future__ import annotations

import json
from importlib.resources import files

from traceweave.models import Plan, ResearchSpec, SourceView
from traceweave.providers.base import LLMError, LLMProvider
from traceweave.skills import SkillRegistry


def _prompt(name: str) -> str:
    return files("traceweave.prompts").joinpath(name).read_text(encoding="utf-8")


class Planner:
    def __init__(self, provider: LLMProvider | None):
        self.provider = provider
        self.skills = SkillRegistry()

    async def initial(self, spec: ResearchSpec, *, run_id: str | None = None) -> Plan:
        if self.provider is None:
            return self._heuristic(spec, round_no=1, completed=[])
        payload = {"topic": spec.topic, "angle": spec.angle, "mode": spec.mode, "language": spec.language, "round": 1}
        try:
            data = await self.provider.json(
                system=_prompt("initial_plan.txt") + "\n\n" + self.skills.for_task("planning"), user=json.dumps(payload, ensure_ascii=False, indent=2),
                task="planning", run_id=run_id,
            )
            return self._normalize_plan(Plan.model_validate(data), spec, [])
        except (LLMError, ValueError):
            return self._heuristic(spec, round_no=1, completed=[])

    async def replan(self, spec: ResearchSpec, *, round_no: int, completed_queries: list[str],
                     sources: list[SourceView], claims: list[dict] | None = None, run_id: str | None = None) -> Plan:
        if self.provider is None:
            return self._heuristic(spec, round_no=round_no, completed=completed_queries)
        capsules = []
        for source in sources[:35]:
            capsules.append({
                "source_id": source.id, "title": source.title, "domain": source.domain,
                "category": source.category, "published_at": source.published_at,
                "relevance": source.relevance, "importance": source.importance, "novelty": source.novelty,
                "authority": source.authority, "duplicate_of": source.duplicate_of,
                "snippet": source.snippet[:500], "text_excerpt": source.text_excerpt[:700] if source.fetched else "",
            })
        claim_capsules = [
            {"claim": c.get("claim_text", ""), "source_id": c.get("source_id"), "confidence": c.get("confidence"),
             "verified_span": bool(c.get("verified_span"))}
            for c in (claims or [])[:30]
        ]
        payload = {
            "topic": spec.topic, "angle": spec.angle, "mode": spec.mode, "round": round_no,
            "completed_queries": completed_queries[-50:], "source_capsules": capsules,
            "grounded_claim_capsules": claim_capsules,
        }
        try:
            data = await self.provider.json(
                system=_prompt("replan.txt") + "\n\n" + self.skills.for_task("replanning"), user=json.dumps(payload, ensure_ascii=False, indent=2),
                task="replanning", run_id=run_id,
            )
            return self._normalize_plan(Plan.model_validate(data), spec, completed_queries)
        except (LLMError, ValueError):
            return self._heuristic(spec, round_no=round_no, completed=completed_queries)

    def _normalize_plan(self, plan: Plan, spec: ResearchSpec, completed: list[str]) -> Plan:
        done = {q.casefold() for q in completed}
        queries = [q for q in plan.queries if q.casefold() not in done][:7]
        if not queries:
            queries = self._heuristic(spec, round_no=2, completed=completed).queries
        return plan.model_copy(update={"queries": queries})

    def _heuristic(self, spec: ResearchSpec, round_no: int, completed: list[str]) -> Plan:
        topic, angle = spec.topic, spec.angle.strip()
        if round_no == 1:
            candidates = [topic, f'"{topic}" {angle}' if angle else f'"{topic}"', f'"{topic}" official',
                          f'"{topic}" report filetype:pdf', f'"{topic}" news interview']
            focus = ["overview", "primary sources", "documents", "independent reporting"]
            objective = "Map the topic, terminology, source classes, and primary-source candidates."
            gaps = ["core entities", "primary documents", "independent confirmation"]
        elif round_no == 2:
            candidates = [f'"{topic}" history timeline', f'"{topic}" interview OR profile',
                          f'"{topic}" report OR presentation OR PDF', f'"{topic}" site:github.com',
                          f'"{topic}" controversy OR criticism OR dispute']
            focus = ["history", "documents", "technical traces", "counter-evidence"]
            objective = "Follow less-obvious leads and fill source-class gaps from round one."
            gaps = ["historical context", "technical/public traces", "counter-evidence"]
        else:
            candidates = [f'"{topic}" archived OR former OR previously', f'"{topic}" partnership OR supplier OR contract',
                          f'"{topic}" conference OR transcript OR presentation', f'"{topic}" academic OR study OR paper',
                          f'"{topic}" {angle}' if angle else f'"{topic}" details']
            focus = ["historical material", "relationships", "specialist sources", "remaining gaps"]
            objective = "Target unresolved gaps and obscure sources before synthesis."
            gaps = ["single-source claims", "missing primary evidence", "under-covered relationships"]
        done = {q.casefold() for q in completed}
        queries: list[str] = []
        for query in candidates:
            query = " ".join(query.split())
            if query.casefold() not in done and query.casefold() not in {q.casefold() for q in queries}:
                queries.append(query)
        return Plan(
            objective=objective, focus=focus, queries=queries[:5], rationale="Deterministic fallback plan",
            gaps=gaps, source_classes=["official", "independent reporting", "documents", "specialist sources"],
        )
