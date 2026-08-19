from pathlib import Path

from traceweave.fetcher import PageLink, SafeFetcher
from traceweave.frontier import FrontierManager
from traceweave.models import ResearchSpec, SearchResult
from traceweave.storage import Storage


def test_frontier_is_best_first_and_depth_bounded(tmp_path: Path):
    storage = Storage(tmp_path / "db.sqlite", tmp_path / "data"); storage.init()
    spec = ResearchSpec(topic="Acme battery supply chain", mode="deep", max_depth=2, max_frontier_pages=10)
    run = storage.create_run(spec)
    parent_id = storage.add_search_result(run, "q", 1, SearchResult(url="https://acme.example", title="Acme"))
    manager = FrontierManager(storage, SafeFetcher(timeout=1, max_bytes=1000, user_agent="test"), user_agent="test")
    links = [
        PageLink("https://acme.example/reports/battery-supply.pdf", "battery supply report", "citation"),
        PageLink("https://acme.example/privacy", "privacy", "link"),
    ]
    assert manager.add_page_links(run, spec, source_id=parent_id, parent_url="https://acme.example", links=links, depth=1) >= 1
    leased = storage.lease_frontier(run, max_depth=2, min_score=0.0, per_domain_limit=8, limit=10)
    assert leased[0]["url"].endswith("battery-supply.pdf")
    assert leased[0]["score"] > leased[-1]["score"]
