from __future__ import annotations

import asyncio
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
        payload = {
            "topic": spec.topic,
            "angle": spec.angle,
            "mode": spec.mode,
            "language": spec.language,
            "round": 1,
        }
        roles = ["Lead coverage planner"]
        if spec.mode in {"deep", "overnight"}:
            roles.extend(
                [
                    "Primary documents, registries, dates, and independent verification",
                    "People, public social activity, comments, documents, and visual evidence",
                    "Technical infrastructure, code, archives, relationships, and rare leads",
                ]
            )

        async def branch(role: str) -> Plan:
            branch_payload = {**payload, "independent_branch": role}
            system = _prompt("initial_plan.txt") + "\n\n" + self.skills.for_task("planning")
            system += (
                "\n\nYou are an isolated planning branch. Cover only the assigned branch, "
                "return distinct high-information queries, and leave synthesis to the lead. "
                f"Assigned branch: {role}"
            )
            deadline = {"quick": 90, "standard": 150, "deep": 240, "overnight": 360}[spec.mode]
            async with asyncio.timeout(deadline):
                data = await self.provider.json(
                    system=system,
                    user=json.dumps(branch_payload, ensure_ascii=False, indent=2),
                    task="planning",
                    run_id=run_id,
                )
            return Plan.model_validate(data)

        results = await asyncio.gather(*(branch(role) for role in roles), return_exceptions=True)
        plans = [result for result in results if isinstance(result, Plan)]
        if not plans:
            return self._heuristic(spec, round_no=1, completed=[])
        merged = self._merge_initial_plans(plans, spec)
        if len(plans) == 1:
            return merged
        try:
            deadline = {"quick": 60, "standard": 120, "deep": 180, "overnight": 240}[spec.mode]
            async with asyncio.timeout(deadline):
                data = await self.provider.json(
                    system=_prompt("lead_plan.txt") + "\n\n" + self.skills.for_task("planning"),
                    user=json.dumps(
                        {
                            "research": payload,
                            "specialist_plans": [plan.model_dump() for plan in plans],
                            "deterministic_merge": merged.model_dump(),
                        },
                        ensure_ascii=False,
                    ),
                    task="planning",
                    run_id=run_id,
                )
            return self._normalize_plan(Plan.model_validate(data), spec, [])
        except (LLMError, TimeoutError, ValueError, KeyError, TypeError):
            return merged

    def _merge_initial_plans(self, plans: list[Plan], spec: ResearchSpec) -> Plan:
        def unique(values: list[str], limit: int) -> list[str]:
            seen: set[str] = set()
            merged: list[str] = []
            for value in values:
                normalized = " ".join(value.split())
                key = normalized.casefold()
                if normalized and key not in seen:
                    seen.add(key)
                    merged.append(normalized)
                if len(merged) >= limit:
                    break
            return merged

        lead = plans[0]
        combined = Plan(
            objective=lead.objective,
            focus=unique([value for plan in plans for value in plan.focus], 10),
            queries=unique([value for plan in plans for value in plan.queries], 14),
            rationale="Parallel specialist planning branches: "
            + "; ".join(plan.rationale for plan in plans if plan.rationale)[:1200],
            gaps=unique([value for plan in plans for value in plan.gaps], 12),
            source_classes=unique(
                [value for plan in plans for value in plan.source_classes],
                12,
            ),
        )
        return self._normalize_plan(combined, spec, [])

    async def replan(
        self,
        spec: ResearchSpec,
        *,
        round_no: int,
        completed_queries: list[str],
        sources: list[SourceView],
        claims: list[dict] | None = None,
        research_state: dict | None = None,
        observation_capsules: list[dict] | None = None,
        run_id: str | None = None,
    ) -> Plan:
        if self.provider is None:
            plan = self._heuristic(spec, round_no=round_no, completed=completed_queries)
            return self._with_observation_leads(plan, spec, observation_capsules)
        capsules = []
        for source in sources[:35]:
            capsules.append(
                {
                    "source_id": source.id,
                    "title": source.title,
                    "domain": source.domain,
                    "category": source.category,
                    "published_at": source.published_at,
                    "relevance": source.relevance,
                    "importance": source.importance,
                    "novelty": source.novelty,
                    "authority": source.authority,
                    "duplicate_of": source.duplicate_of,
                    "snippet": source.snippet[:500],
                    "text_excerpt": source.text_excerpt[:700] if source.fetched else "",
                }
            )
        claim_capsules = [
            {
                "claim": c.get("claim_text", ""),
                "source_id": c.get("source_id"),
                "confidence": c.get("confidence"),
                "verified_span": bool(c.get("verified_span")),
            }
            for c in (claims or [])[:30]
        ]
        payload = {
            "topic": spec.topic,
            "angle": spec.angle,
            "mode": spec.mode,
            "round": round_no,
            "completed_queries": completed_queries[-50:],
            "source_capsules": capsules,
            "grounded_claim_capsules": claim_capsules,
            "research_state": research_state or {},
            "observation_capsules": observation_capsules or [],
        }
        try:
            deadline = {"quick": 90, "standard": 150, "deep": 240, "overnight": 360}[spec.mode]
            async with asyncio.timeout(deadline):
                data = await self.provider.json(
                    system=_prompt("replan.txt") + "\n\n" + self.skills.for_task("replanning"),
                    user=json.dumps(payload, ensure_ascii=False, indent=2),
                    task="replanning",
                    run_id=run_id,
                )
            plan = self._normalize_plan(Plan.model_validate(data), spec, completed_queries)
            return self._with_observation_leads(plan, spec, observation_capsules)
        except (LLMError, TimeoutError, ValueError):
            plan = self._heuristic(spec, round_no=round_no, completed=completed_queries)
            return self._with_observation_leads(plan, spec, observation_capsules)

    def _with_observation_leads(
        self,
        plan: Plan,
        spec: ResearchSpec,
        observations: list[dict] | None,
    ) -> Plan:
        """Promote concise visual/OCR observations into traceable discovery queries."""
        query_limit = 12 if spec.mode in {"deep", "overnight"} else 7
        lead_queries: list[str] = []
        seen = {query.casefold() for query in plan.queries}
        for observation in observations or []:
            kind = str(observation.get("kind") or "")
            if not kind.startswith(("ocr:", "vision:")):
                continue
            text = " ".join(str(observation.get("text") or "").split())
            if not 2 <= len(text) <= 180:
                continue
            query = f'"{text}" "{spec.topic}"'
            if query.casefold() in seen:
                continue
            lead_queries.append(query)
            seen.add(query.casefold())
            if len(lead_queries) >= 4:
                break
        queries = lead_queries + list(plan.queries)
        return plan.model_copy(update={"queries": queries[:query_limit]})

    def _normalize_plan(self, plan: Plan, spec: ResearchSpec, completed: list[str]) -> Plan:
        done = {q.casefold() for q in completed}
        query_limit = 12 if spec.mode in {"deep", "overnight"} else 7
        queries = [q for q in plan.queries if q.casefold() not in done][:query_limit]
        if not queries:
            queries = self._heuristic(spec, round_no=2, completed=completed).queries
        return plan.model_copy(update={"queries": queries})

    def _heuristic(self, spec: ResearchSpec, round_no: int, completed: list[str]) -> Plan:
        topic, angle = spec.topic, spec.angle.strip()
        if round_no == 1:
            candidates = [
                topic,
                f'"{topic}" {angle}' if angle else f'"{topic}"',
                f'"{topic}" official',
                f'"{topic}" report filetype:pdf',
                f'"{topic}" news interview',
            ]
            focus = ["overview", "primary sources", "documents", "independent reporting"]
            objective = "Map the topic, terminology, source classes, and primary-source candidates."
            gaps = ["core entities", "primary documents", "independent confirmation"]
        elif round_no == 2:
            candidates = [
                f'"{topic}" history timeline',
                f'"{topic}" interview OR profile',
                f'"{topic}" report OR presentation OR PDF',
                f'"{topic}" site:github.com',
                f'"{topic}" controversy OR criticism OR dispute',
                f'site:linkedin.com/in "{topic}"',
                f'site:linkedin.com/posts "{topic}"',
                f'site:t.me "{topic}"',
                f'site:instagram.com "{topic}"',
            ]
            focus = ["history", "documents", "technical traces", "counter-evidence"]
            objective = "Follow less-obvious leads and fill source-class gaps from round one."
            gaps = ["historical context", "technical/public traces", "counter-evidence"]
        else:
            candidates = [
                f'"{topic}" archived OR former OR previously',
                f'"{topic}" partnership OR supplier OR contract',
                f'"{topic}" conference OR transcript OR presentation',
                f'"{topic}" academic OR study OR paper',
                f'"{topic}" {angle}' if angle else f'"{topic}" details',
                f'"{topic}" employee presentation photo',
                f'"{topic}" product codename prototype',
            ]
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
            objective=objective,
            focus=focus,
            queries=queries[:7] if spec.mode in {"deep", "overnight"} else queries[:5],
            rationale="Deterministic fallback plan",
            gaps=gaps,
            source_classes=["official", "independent reporting", "documents", "academic", "archives", "code"],
        )
