from __future__ import annotations

from pathlib import Path

import pytest

from traceweave.analysis import EvidenceAnalyzer
from traceweave.models import ResearchSpec, SearchResult
from traceweave.storage import Storage


class FakeProvider:
    name = "fake"

    async def json(self, *, system, user, task="general", run_id=None):
        if task == "claim_extraction":
            return {
                "claims": [
                    {"claim": "A valid claim", "evidence_quote": "exact evidence", "confidence": 0.9},
                    {"claim": "Ungrounded", "evidence_quote": "not in source", "confidence": 0.9},
                ]
            }
        return {"relevance": 90, "importance": 80, "novelty": 70, "authority": 60, "rationale": "x"}

    async def text(self, *, system, user, task="general", run_id=None):
        return ""


@pytest.mark.asyncio
async def test_claim_extractor_rejects_non_literal_quotes(tmp_path: Path):
    storage = Storage(tmp_path / "db.sqlite", tmp_path / "data")
    storage.init()
    run = storage.create_run(ResearchSpec(topic="example"))
    storage.add_search_result(run, "q", 1, SearchResult(url="https://example.com", title="x"))
    source = storage.sources_for_run(run)[0].model_copy(
        update={"text_excerpt": "some exact evidence in source"}
    )
    claims = await EvidenceAnalyzer(storage, FakeProvider()).extract_claims(
        run, ResearchSpec(topic="example"), source
    )
    assert len(claims) == 1
    assert claims[0].claim == "A valid claim"
