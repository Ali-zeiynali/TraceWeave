"""Offline Stage-2/3 smoke: plan -> search -> evidence -> best-first frontier -> re-plan -> synthesize."""
from __future__ import annotations

import asyncio
import hashlib
import tempfile
from pathlib import Path

from traceweave.config import Settings
from traceweave.engine import ResearchEngine
from traceweave.fetcher import FetchResult, PageLink
from traceweave.models import ResearchSpec, SearchResult
from traceweave.planner import Planner
from traceweave.storage import Storage
from traceweave.utils import simhash64


class FakeSearch:
    name = "fake"
    async def search(self, query: str, *, limit: int, language: str):
        del limit, language
        return [SearchResult(url="https://example.com/root", title="Root report", snippet="battery evidence", engine="fake")]


class FakeProvider:
    name = "fake"
    async def json(self, *, system: str, user: str, task: str = "general", run_id: str | None = None):
        del system, user, run_id
        if task in {"planning", "replanning"}:
            return {"objective": "find evidence", "focus": ["documents"], "queries": ["synthetic battery report"],
                    "gaps": ["confirmation"], "source_classes": ["documents"], "rationale": "smoke"}
        if task == "triage":
            return {"relevance": 90, "importance": 85, "novelty": 75, "authority": 70, "rationale": "smoke",
                    "topics": ["battery"], "leads": ["child document"]}
        if task == "claim_extraction":
            return {"claims": [{"claim": "The synthetic source contains evidence.",
                                  "evidence_quote": "synthetic evidence", "confidence": 0.95}]}
        return {}
    async def text(self, *, system: str, user: str, task: str = "general", run_id: str | None = None):
        del system, user, task, run_id
        return "Synthetic synthesis [S1]."


class OfflineEngine(ResearchEngine):
    async def _fetch_source(self, run_id: str, spec: ResearchSpec, source_id: int, url: str, *, depth: int):
        text = f"synthetic evidence for {url}"
        raw = f"<html><body>{text}</body></html>".encode()
        links = [] if "child" in url else [PageLink("https://example.com/child", "child battery document", "citation")]
        result = FetchResult(
            final_url=url, status_code=200, content_type="text/html", raw=raw, text=text, title="Synthetic",
            content_hash=hashlib.sha256(raw).hexdigest(), simhash=simhash64(text), links=links,
        )
        self.storage.save_snapshot(
            source_id=source_id, final_url=url, status_code=200, content_type="text/html",
            content_hash=result.content_hash, raw=raw, text=text, extracted_title="Synthetic", simhash=result.simhash,
        )
        if depth < spec.resolved_depth():
            self.frontier.add_page_links(run_id, spec, source_id=source_id, parent_url=url, links=links, depth=depth + 1)
        return result


async def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        settings = Settings(
            data_dir=root / "data", triage_enabled=True, claims_enabled=True,
            sitemap_enabled=False, respect_robots=False, frontier_min_score=0.0,
        )
        settings.ensure_dirs()
        storage = Storage(settings.db_path, settings.data_dir); storage.init()
        provider = FakeProvider()
        engine = OfflineEngine(
            settings=settings, storage=storage, search=FakeSearch(), planner=Planner(provider), provider=provider,
        )
        run_id = await engine.start(ResearchSpec(
            topic="synthetic battery", mode="standard", max_rounds=2, max_depth=2,
            max_frontier_pages=2, fetch_top_per_query=1,
        ))
        row = storage.get_run(run_id)
        assert row and row["status"] == "completed" and row["current_round"] == 2
        assert len(storage.sources_for_run(run_id)) >= 2
        assert storage.claims_for_run(run_id)
        assert storage.frontier_stats(run_id).get("completed", 0) >= 1
        print(f"STAGE23 SMOKE OK: {run_id}")


if __name__ == "__main__":
    asyncio.run(main())
