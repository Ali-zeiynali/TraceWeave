from __future__ import annotations

import json
from importlib.resources import files

from traceweave.models import Plan, ResearchSpec, SourceView
from traceweave.providers.base import LLMProvider


def _prompt(name: str) -> str:
    return files("traceweave.prompts").joinpath(name).read_text(encoding="utf-8")


class Planner:
    def __init__(self, provider: LLMProvider | None):
        self.provider = provider

    async def initial(self, spec: ResearchSpec) -> Plan:
        if self.provider is None:
            return self._heuristic(spec, round_no=1, completed=[])
        payload = {
            "topic": spec.topic,
            "angle": spec.angle,
            "mode": spec.mode,
            "language": spec.language,
            "round": 1,
        }
        data = await self.provider.json(
            system=_prompt("initial_plan.txt"),
            user=json.dumps(payload, ensure_ascii=False, indent=2),
        )
        return self._normalize_plan(Plan.model_validate(data), spec, [])

    async def replan(
        self,
        spec: ResearchSpec,
        *,
        round_no: int,
        completed_queries: list[str],
        sources: list[SourceView],
    ) -> Plan:
        if self.provider is None:
            return self._heuristic(spec, round_no=round_no, completed=completed_queries)
        capsules = []
        for source in sources[:30]:
            capsules.append({
                "source_id": source.id,
                "title": source.title,
                "domain": source.domain,
                "category": source.category,
                "published_at": source.published_at,
                "snippet": source.snippet[:600],
                "text_excerpt": source.text_excerpt[:900] if source.fetched else "",
            })
        payload = {
            "topic": spec.topic,
            "angle": spec.angle,
            "mode": spec.mode,
            "round": round_no,
            "completed_queries": completed_queries[-40:],
            "source_capsules": capsules,
        }
        data = await self.provider.json(
            system=_prompt("replan.txt"),
            user=json.dumps(payload, ensure_ascii=False, indent=2),
        )
        return self._normalize_plan(Plan.model_validate(data), spec, completed_queries)

    def _normalize_plan(self, plan: Plan, spec: ResearchSpec, completed: list[str]) -> Plan:
        done = {q.casefold() for q in completed}
        queries = [q for q in plan.queries if q.casefold() not in done][:6]
        if not queries:
            queries = self._heuristic(spec, round_no=2, completed=completed).queries
        return plan.model_copy(update={"queries": queries})

    def _heuristic(self, spec: ResearchSpec, round_no: int, completed: list[str]) -> Plan:
        topic = spec.topic
        angle = spec.angle.strip()
        if round_no == 1:
            candidates = [
                topic,
                f'"{topic}" {angle}' if angle else f'"{topic}"',
                f'"{topic}" official',
                f'"{topic}" report filetype:pdf',
                f'"{topic}" news interview',
            ]
            focus = ["overview", "primary sources", "documents", "reporting"]
            objective = "Map the topic, terminology, source classes, and primary-source candidates."
        elif round_no == 2:
            candidates = [
                f'"{topic}" history timeline',
                f'"{topic}" interview OR profile',
                f'"{topic}" report OR presentation OR PDF',
                f'"{topic}" site:github.com',
                f'"{topic}" controversy OR criticism OR dispute',
            ]
            focus = ["history", "documents", "technical traces", "counter-evidence"]
            objective = "Follow less obvious leads and fill source-class gaps from round one."
        else:
            candidates = [
                f'"{topic}" archived OR former OR previously',
                f'"{topic}" partnership OR supplier OR contract',
                f'"{topic}" conference OR transcript OR presentation',
                f'"{topic}" academic OR study OR paper',
                f'"{topic}" {angle}' if angle else f'"{topic}" details',
            ]
            focus = ["historical material", "relationships", "specialist sources", "remaining gaps"]
            objective = "Target unresolved gaps and obscure sources before synthesis."
        done = {q.casefold() for q in completed}
        queries = []
        for query in candidates:
            query = " ".join(query.split())
            if query.casefold() not in done and query.casefold() not in {q.casefold() for q in queries}:
                queries.append(query)
        return Plan(objective=objective, focus=focus, queries=queries[:5], rationale="Deterministic fallback plan")
