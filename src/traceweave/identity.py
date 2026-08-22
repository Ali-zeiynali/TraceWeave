from __future__ import annotations

import json
from importlib.resources import files

from traceweave.models import ResearchSpec
from traceweave.providers.base import LLMError, LLMProvider
from traceweave.storage import Storage
from traceweave.utils import words


class IdentityResolver:
    """Create reviewable identity hypotheses; never merge people automatically."""

    def __init__(self, storage: Storage, provider: LLMProvider | None):
        self.storage = storage
        self.provider = provider

    async def resolve(self, run_id: str, spec: ResearchSpec) -> dict[str, int]:
        media = self._match_media(run_id)
        people = [e for e in self.storage.entities_for_run(run_id, 300) if e["entity_type"] == "person"]
        aliases = self.storage.entity_aliases_for_run(run_id)
        candidates = self._candidate_pairs(people, aliases)
        saved = 0
        if candidates and self.provider is not None:
            claims = self.storage.claims_for_run(run_id, 300)
            by_claim = {int(claim["id"]): claim for claim in claims}
            try:
                prompt = files("traceweave.prompts").joinpath("identity.txt").read_text(encoding="utf-8")
                payload = await self.provider.json(
                    system=prompt,
                    user=json.dumps(
                        {
                            "research": {"topic": spec.topic, "angle": spec.angle},
                            "candidate_pairs": candidates,
                            "claims": [
                                {
                                    "id": claim["id"],
                                    "claim": claim["claim_text"],
                                    "source_id": claim["source_id"],
                                    "domain": claim.get("domain", ""),
                                }
                                for claim in claims
                            ],
                            "media_matches": self.storage.artifact_matches_for_run(run_id, 100),
                        },
                        ensure_ascii=False,
                    ),
                    task="entity_extraction",
                    run_id=run_id,
                )
            except (LLMError, ValueError, TypeError):
                payload = {}
            allowed_pairs = {
                (int(item["left_entity_id"]), int(item["right_entity_id"])) for item in candidates
            }
            for item in payload.get("hypotheses", [])[: len(candidates)]:
                try:
                    pair = tuple(sorted((int(item["left_entity_id"]), int(item["right_entity_id"]))))
                except (TypeError, ValueError):
                    continue
                if pair not in allowed_pairs:
                    continue
                evidence = [
                    int(value)
                    for value in item.get("evidence_claim_ids", [])
                    if str(value).isdigit() and int(value) in by_claim
                ]
                domains = {str(by_claim[value].get("domain") or "") for value in evidence}
                verdict = str(item.get("verdict") or "uncertain")
                # A model-only name/face impression is never enough to assert identity.
                if verdict == "same" and (len(evidence) < 2 or len({d for d in domains if d}) < 2):
                    verdict = "uncertain"
                if verdict not in {"same", "different", "uncertain"}:
                    verdict = "uncertain"
                self.storage.save_identity_hypothesis(
                    run_id,
                    pair[0],
                    pair[1],
                    verdict=verdict,
                    confidence=float(item.get("confidence") or 0.5),
                    evidence_claim_ids=evidence,
                    rationale=str(item.get("rationale") or ""),
                )
                saved += 1
        return {"identity_hypotheses": saved, "media_matches": media}

    @staticmethod
    def _candidate_pairs(people: list[dict], aliases: dict[int, list[str]]) -> list[dict]:
        pairs: list[dict] = []
        for index, left in enumerate(people):
            left_names = [str(left["canonical_name"]), *aliases.get(int(left["id"]), [])]
            left_words = set().union(*(words(name) for name in left_names))
            for right in people[index + 1 :]:
                right_names = [str(right["canonical_name"]), *aliases.get(int(right["id"]), [])]
                right_words = set().union(*(words(name) for name in right_names))
                shared = left_words & right_words
                if not shared or len(shared) / max(1, min(len(left_words), len(right_words))) < 0.5:
                    continue
                pairs.append(
                    {
                        "left_entity_id": int(left["id"]),
                        "left_names": left_names,
                        "right_entity_id": int(right["id"]),
                        "right_names": right_names,
                        "shared_name_tokens": sorted(shared),
                    }
                )
                if len(pairs) >= 40:
                    return pairs
        return pairs

    def _match_media(self, run_id: str) -> int:
        observations = [
            item
            for item in self.storage.observations_for_run(run_id, 5000)
            if item.get("kind") == "media:phash" and item.get("artifact_id")
        ]
        saved = 0
        for index, left in enumerate(observations):
            try:
                left_hash = int(str(left["value_text"]), 16)
            except ValueError:
                continue
            for right in observations[index + 1 :]:
                if left["artifact_id"] == right["artifact_id"]:
                    continue
                try:
                    distance = (left_hash ^ int(str(right["value_text"]), 16)).bit_count()
                except ValueError:
                    continue
                if distance > 10:
                    continue
                verdict = "same_image" if distance == 0 else "near_duplicate"
                self.storage.save_artifact_match(
                    run_id,
                    str(left["artifact_id"]),
                    str(right["artifact_id"]),
                    algorithm="phash64",
                    distance=float(distance),
                    verdict=verdict,
                )
                saved += 1
        return saved
