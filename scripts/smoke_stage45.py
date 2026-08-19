from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from traceweave.config import Settings
from traceweave.engine import ResearchEngine
from traceweave.fetcher import FetchResult
from traceweave.models import ResearchSpec, SearchResult
from traceweave.planner import Planner
from traceweave.sources.archives import ArchiveCapture
from traceweave.sources.common import SpecialistResult
from traceweave.storage import Storage
from traceweave.utils import simhash64


class FakeSearch:
    name = "fake"
    async def search(self, query: str, *, limit: int, language: str):
        del language
        return [SearchResult(url="https://example.org/current", title="Acme current", snippet="Acme acquired Beta in 2025", engine="fake", category="web")][:limit]


class FakeProvider:
    name = "fake"
    async def json(self, *, system: str, user: str, task="general", run_id=None):
        if task == "triage":
            return {"relevance": 95, "importance": 90, "novelty": 75, "authority": 80, "rationale": "fixture", "topics": ["Acme"], "leads": ["Beta"]}
        if task == "claim_extraction":
            return {"claims": [{"claim": "Acme acquired Beta in 2025", "subject": "Acme", "predicate": "acquired", "object": "Beta", "observed_at": "2025", "evidence_quote": "Acme acquired Beta in 2025", "confidence": .92}]}
        if task == "entity_extraction":
            # Includes one invalid relationship to verify GraphCurator ignores ungrounded claim ids.
            return {"entities": [{"name": "Acme", "type": "organization", "confidence": .95}, {"name": "Beta", "type": "organization", "confidence": .9}],
                    "relationships": [{"source": "Acme", "predicate": "acquired", "target": "Beta", "claim_id": 1, "confidence": .9},
                                      {"source": "Acme", "predicate": "invented", "target": "Ghost", "claim_id": 99999, "confidence": 1.0}]}
        return {}
    async def text(self, *, system: str, user: str, task="general", run_id=None):
        return "Grounded fixture synthesis [S1]."


class FakeFetcher:
    async def fetch(self, url: str, max_redirects: int = 5, accept=None, max_bytes=None):
        del max_redirects, accept, max_bytes
        if "archive.org" in url:
            text = "Archived Acme page from 2024."
        elif "github.com" in url:
            text = "Public repository notes about Acme."
        elif "doi.org" in url:
            text = "Academic landing page about Acme."
        else:
            text = "Acme acquired Beta in 2025. See doi:10.1000/xyz123 and https://example.org/reference.pdf"
        raw = text.encode()
        return FetchResult(final_url=url, status_code=200, content_type="text/html", raw=raw, text=text,
                           title="fixture", content_hash="hash-" + str(abs(hash(url))), simhash=simhash64(text), links=[], feeds=[])


class FakeAcademic:
    async def search(self, query: str, limit: int):
        return [SpecialistResult(url="https://doi.org/10.1000/xyz123", title="Acme paper", snippet="paper", engine="openalex", category="academic")][:limit]


class FakeGitHub:
    async def search(self, query: str, limit: int):
        return [SpecialistResult(url="https://github.com/example/acme", title="example/acme", snippet="repo", engine="github-repositories", category="code")][:limit]


class FakeWayback:
    async def captures(self, url: str, limit: int):
        return [ArchiveCapture(engine="wayback", original_url=url, capture_url="https://web.archive.org/web/20240101000000id_/https://example.org/current", captured_at="20240101000000", mime="text/html", status=200, digest="d1", raw={"fixture": True})][:limit]


class FakeCommonCrawl:
    async def captures(self, url: str, limit: int):
        return [ArchiveCapture(engine="commoncrawl", original_url=url, capture_url="ccwarc://fixture#0:50", captured_at="20230101000000", mime="text/html", status=200, digest="cc1", raw={"filename": "fixture", "offset": 0, "length": 50})][:limit]
    async def fetch_capture(self, capture, *, max_bytes: int):
        del capture, max_bytes
        return b"<html><body>Common Crawl historical Acme</body></html>", "text/html"


async def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        settings = Settings(data_dir=root / "data", respect_robots=False, sitemap_enabled=False,
                            browser_fallback=False)
        settings.ensure_dirs()
        storage = Storage(settings.db_path, settings.data_dir); storage.init()
        provider = FakeProvider()
        engine = ResearchEngine(settings=settings, storage=storage, search=FakeSearch(), planner=Planner(None), provider=provider)
        engine.fetcher = FakeFetcher()
        engine.specialists.fetcher = engine.fetcher
        engine.specialists.academic = FakeAcademic(); engine.specialists.github = FakeGitHub()
        engine.specialists.wayback = FakeWayback(); engine.specialists.commoncrawl = FakeCommonCrawl()
        spec = ResearchSpec(topic="Acme technology", angle="history and technical evidence", mode="deep", max_rounds=2,
                            max_results_per_query=1, fetch_top_per_query=1, max_depth=1, max_frontier_pages=4)
        run_id = await engine.start(spec)
        assert storage.get_run(run_id)["status"] == "completed"
        assert storage.claims_for_run(run_id), "grounded claims missing"
        assert storage.archive_captures_for_run(run_id), "archive captures missing"
        assert storage.citations_for_run(run_id), "citation snowballing missing"
        assert storage.entities_for_run(run_id), "entities missing"
        assert storage.relationships_for_run(run_id), "relationships missing"
        assert storage.timeline_for_run(run_id), "timeline missing"
        assert not any(r["predicate"] == "invented" for r in storage.relationships_for_run(run_id)), "ungrounded graph relation admitted"
        # Archive source state should avoid repeating successful archive API work on the second round.
        current = next(s for s in storage.sources_for_run(run_id, 500) if s.url == "https://example.org/current")
        assert storage.source_stage_state(run_id, current.id, "archive:wayback")["status"] == "done"
        print("SMOKE_STAGE45_OK", run_id, len(storage.sources_for_run(run_id, 500)), len(storage.claims_for_run(run_id, 500)))


if __name__ == "__main__":
    asyncio.run(main())
