from __future__ import annotations

import json
from importlib.resources import files

from traceweave.models import ResearchSpec
from traceweave.providers.base import LLMError, LLMProvider
from traceweave.skills import SkillRegistry
from traceweave.storage import Storage
from traceweave.utils import lexical_overlap


class ClaimVerifier:
    """Assess claim support without promoting model prose to evidence.

    The model may point out relationships between already-grounded claims. Verdicts are
    constrained by stored claim ids and a corroborated verdict requires distinct domains.
    """

    def __init__(self, storage: Storage, provider: LLMProvider | None):
        self.storage = storage
        self.provider = provider
        self.skills = SkillRegistry()

    async def assess(self, run_id: str, spec: ResearchSpec) -> dict[str, int]:
        claims = self.storage.claims_for_run(run_id, 240)
        if not claims:
            return {}
        by_id = {int(claim["id"]): claim for claim in claims}
        assessments = self._deterministic(claims)
        if self.provider is not None:
            prompt = files("traceweave.prompts").joinpath("verification.txt").read_text(encoding="utf-8")
            try:
                payload = await self.provider.json(
                    system=prompt + "\n\n" + self.skills.for_task("verification"),
                    user=json.dumps(
                        {
                            "research": {"topic": spec.topic, "angle": spec.angle},
                            "claims": [
                                {
                                    "id": claim["id"],
                                    "claim": claim["claim_text"],
                                    "quote": claim.get("quote", "")[:800],
                                    "source_id": claim["source_id"],
                                    "domain": claim.get("domain", ""),
                                    "published_at": claim.get("observed_at"),
                                }
                                for claim in claims
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    task="verification",
                    run_id=run_id,
                )
                assessments = self._validate_model(payload, by_id, assessments)
            except (LLMError, ValueError, TypeError):
                pass

        counts: dict[str, int] = {}
        for claim_id, assessment in assessments.items():
            self.storage.save_claim_assessment(run_id, claim_id, **assessment)
            verdict = str(assessment["verdict"])
            counts[verdict] = counts.get(verdict, 0) + 1
        return counts

    @staticmethod
    def _deterministic(claims: list[dict]) -> dict[int, dict]:
        out: dict[int, dict] = {}
        for claim in claims:
            claim_id = int(claim["id"])
            supports = [claim_id]
            domains = {str(claim.get("domain") or "")}
            for other in claims:
                other_id = int(other["id"])
                if other_id == claim_id:
                    continue
                overlap = lexical_overlap(str(claim["claim_text"]), str(other["claim_text"]))
                same_relation = bool(
                    claim.get("subject")
                    and claim.get("predicate")
                    and str(claim.get("subject")).casefold() == str(other.get("subject")).casefold()
                    and str(claim.get("predicate")).casefold() == str(other.get("predicate")).casefold()
                )
                if overlap >= 0.72 or (same_relation and overlap >= 0.45):
                    supports.append(other_id)
                    domains.add(str(other.get("domain") or ""))
            corroborated = len({domain for domain in domains if domain}) >= 2
            out[claim_id] = {
                "verdict": "corroborated" if corroborated else "single_source",
                "confidence": 0.82 if corroborated else 0.55,
                "supporting_claim_ids": supports,
                "conflicting_claim_ids": [],
                "rationale": (
                    "Independent-domain lexical/relation match."
                    if corroborated
                    else "No independent-domain grounded claim matched this proposition."
                ),
            }
        return out

    @staticmethod
    def _validate_model(payload: dict, by_id: dict[int, dict], fallback: dict[int, dict]) -> dict[int, dict]:
        out = dict(fallback)
        for item in payload.get("assessments", [])[: len(by_id)]:
            try:
                claim_id = int(item.get("claim_id"))
            except (TypeError, ValueError):
                continue
            if claim_id not in by_id:
                continue
            support = [
                int(value)
                for value in item.get("supporting_claim_ids", [])
                if str(value).isdigit() and int(value) in by_id
            ]
            conflicts = [
                int(value)
                for value in item.get("conflicting_claim_ids", [])
                if str(value).isdigit()
                and int(value) in by_id
                and int(value) != claim_id
                and ClaimVerifier._plausible_conflict(by_id[claim_id], by_id[int(value)])
            ]
            if claim_id not in support:
                support.insert(0, claim_id)
            domains = {str(by_id[value].get("domain") or "") for value in support}
            verdict = str(item.get("verdict") or "insufficient")
            if conflicts:
                verdict = "contested"
            elif verdict == "contested":
                verdict = str(fallback[claim_id]["verdict"])
            elif verdict == "corroborated" and len({domain for domain in domains if domain}) < 2:
                verdict = "single_source"
            elif verdict not in {"corroborated", "single_source", "contested", "insufficient"}:
                verdict = "insufficient"
            out[claim_id] = {
                "verdict": verdict,
                "confidence": float(item.get("confidence") or 0.5),
                "supporting_claim_ids": support,
                "conflicting_claim_ids": conflicts,
                "rationale": str(item.get("rationale") or "")[:2000],
            }
        return out

    @staticmethod
    def _plausible_conflict(left: dict, right: dict) -> bool:
        """Reject model-proposed contradictions between different event attributes.

        A deprecation date and an end-of-life date can differ without conflict. Keep the gate
        conservative: subjects and predicates must describe substantially the same relation.
        """
        left_subject = str(left.get("subject") or "")
        right_subject = str(right.get("subject") or "")
        left_predicate = str(left.get("predicate") or "")
        right_predicate = str(right.get("predicate") or "")
        if not all((left_subject, right_subject, left_predicate, right_predicate)):
            return False
        return (
            lexical_overlap(left_subject, right_subject) >= 0.6
            and lexical_overlap(left_predicate, right_predicate) >= 0.6
        )
