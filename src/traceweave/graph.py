from __future__ import annotations

import json
from importlib.resources import files

from traceweave.models import ResearchSpec
from traceweave.providers.base import LLMError, LLMProvider
from traceweave.storage import Storage


class GraphCurator:
    """Grounded Stage-5 foundation built from already stored claims/evidence.

    LLM output may normalize names/types, but it cannot invent relationship evidence: every relationship
    must point at a claim id that exists in the run. A deterministic fallback still creates useful graph state.
    """
    def __init__(self, storage: Storage, provider: LLMProvider | None):
        self.storage = storage
        self.provider = provider

    async def curate(self, run_id: str, spec: ResearchSpec) -> dict[str, int]:
        claims = self.storage.claims_for_run(run_id, 300)
        if not claims:
            return {"entities": 0, "relationships": 0, "timeline": 0}
        by_id = {int(c["id"]): c for c in claims}
        payload: dict | None = None
        if self.provider is not None:
            try:
                prompt = files("traceweave.prompts").joinpath("entities.txt").read_text(encoding="utf-8")
                payload = await self.provider.json(
                    system=prompt,
                    user=json.dumps({"topic": spec.topic, "angle": spec.angle, "claims": [
                        {"id": c["id"], "source_id": c["source_id"], "claim": c["claim_text"], "subject": c["subject"],
                         "predicate": c["predicate"], "object": c["object_text"], "observed_at": c["observed_at"], "confidence": c["confidence"]}
                        for c in claims
                    ]}, ensure_ascii=False),
                    task="entity_extraction", run_id=run_id,
                )
            except (LLMError, ValueError):
                payload = None
        if not payload:
            payload = self._fallback(claims)
        entity_map: dict[str, int] = {}
        entity_count = relationship_count = timeline_count = 0
        for item in payload.get("entities", [])[:250]:
            name = " ".join(str(item.get("name") or "").split()).strip()
            if not name: continue
            eid = self.storage.upsert_entity(
                run_id, name=name, entity_type=str(item.get("type") or "unknown")[:40],
                description=str(item.get("description") or "")[:1000], confidence=_prob(item.get("confidence"), .65),
                aliases=[str(x) for x in item.get("aliases", [])[:12]],
            )
            entity_map[name.casefold()] = eid; entity_count += 1
            self.storage.add_research_edge(run_id, from_type="run", from_id=run_id, relation="contains_entity", to_type="entity", to_id=eid)
        for item in payload.get("relationships", [])[:400]:
            try: claim_id = int(item.get("claim_id"))
            except (TypeError, ValueError): continue
            claim = by_id.get(claim_id)
            if not claim: continue
            src_name = " ".join(str(item.get("source") or claim.get("subject") or "").split()).strip()
            dst_name = " ".join(str(item.get("target") or claim.get("object_text") or "").split()).strip()
            if not src_name: continue
            src = entity_map.get(src_name.casefold()) or self.storage.upsert_entity(run_id, name=src_name)
            dst = None
            if dst_name:
                dst = entity_map.get(dst_name.casefold()) or self.storage.upsert_entity(run_id, name=dst_name)
            rid = self.storage.add_relationship(
                run_id, source_entity_id=src, predicate=str(item.get("predicate") or claim.get("predicate") or "related_to")[:100],
                target_entity_id=dst, target_text="" if dst else dst_name, claim_id=claim_id,
                source_id=int(claim["source_id"]), confidence=min(_prob(item.get("confidence"), .6), float(claim.get("confidence") or .5)),
            )
            if rid:
                relationship_count += 1
                self.storage.add_research_edge(run_id, from_type="claim", from_id=claim_id, relation="supports_relationship", to_type="relationship", to_id=rid)
        # Timeline is deterministically grounded in claim dates, never invented by graph normalization.
        for claim in claims:
            when = str(claim.get("observed_at") or "").strip()
            if not when: continue
            subject = str(claim.get("subject") or "").strip()
            eid = entity_map.get(subject.casefold()) if subject else None
            tid = self.storage.add_timeline_event(
                run_id, event_time=when, label=str(claim["claim_text"])[:1200], entity_id=eid,
                claim_id=int(claim["id"]), source_id=int(claim["source_id"]), confidence=float(claim.get("confidence") or .5),
            )
            if tid:
                timeline_count += 1
                self.storage.add_research_edge(run_id, from_type="claim", from_id=claim["id"], relation="timeline_event", to_type="timeline", to_id=tid)
        return {"entities": entity_count, "relationships": relationship_count, "timeline": timeline_count}

    @staticmethod
    def _fallback(claims: list[dict]) -> dict:
        entities: dict[str, dict] = {}
        relationships = []
        for c in claims:
            subject = " ".join(str(c.get("subject") or "").split()).strip()
            obj = " ".join(str(c.get("object_text") or "").split()).strip()
            if subject:
                entities.setdefault(subject.casefold(), {"name": subject, "type": "unknown", "confidence": c.get("confidence", .5), "aliases": []})
            if obj and len(obj) <= 160:
                entities.setdefault(obj.casefold(), {"name": obj, "type": "unknown", "confidence": c.get("confidence", .5), "aliases": []})
            if subject:
                relationships.append({"source": subject, "predicate": c.get("predicate") or "related_to", "target": obj, "claim_id": c["id"], "confidence": c.get("confidence", .5)})
        return {"entities": list(entities.values()), "relationships": relationships}


def _prob(value, default: float) -> float:
    try: return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError): return default
