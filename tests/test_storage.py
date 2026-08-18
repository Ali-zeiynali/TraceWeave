from pathlib import Path

from traceweave.models import Plan, ResearchSpec, SearchResult
from traceweave.storage import Storage


def test_storage_preserves_search_provenance(tmp_path: Path):
    storage = Storage(tmp_path / "db.sqlite", tmp_path / "data")
    storage.init()
    run_id = storage.create_run(ResearchSpec(topic="Example topic", max_rounds=2))
    storage.save_plan(run_id, 1, Plan(objective="map", queries=["example query"]))
    sid = storage.add_search_result(
        run_id,
        "example query",
        1,
        SearchResult(
            url="https://example.com/news?utm_source=test",
            title="Example News",
            snippet="A stored snippet",
            engine="test-engine",
            category="news",
            published_at="2026-08-01",
            raw={"source": "fixture"},
        ),
    )
    storage.add_search_result(
        run_id,
        "second query",
        3,
        SearchResult(
            url="https://example.com/news",
            title="Example News",
            snippet="Second discovery",
            engine="other-engine",
            category="web",
        ),
    )
    sources = storage.sources_for_run(run_id)
    assert len(sources) == 1
    assert sources[0].id == sid
    assert sources[0].search_query == "example query"
    assert sources[0].engine == "test-engine"
    assert sources[0].category == "news"
    assert sources[0].canonical_url == "https://example.com/news"


def test_all_discovery_paths_are_exportable(tmp_path: Path):
    storage = Storage(tmp_path / "db.sqlite", tmp_path / "data")
    storage.init()
    run_id = storage.create_run(ResearchSpec(topic="Discovery paths"))
    result = SearchResult(url="https://example.com/a", title="A", engine="e1")
    sid = storage.add_search_result(run_id, "q1", 1, result)
    storage.add_search_result(run_id, "q2", 2, result.model_copy(update={"engine": "e2"}))
    paths = storage.source_discoveries(run_id, sid)
    assert [p["search_query"] for p in paths] == ["q1", "q2"]
    assert len(storage.discoveries_for_run(run_id)) == 2


def test_same_query_same_url_keeps_distinct_engines_and_categories(tmp_path: Path):
    storage = Storage(tmp_path / "db.sqlite", tmp_path / "data")
    storage.init()
    run_id = storage.create_run(ResearchSpec(topic="Provenance multiplicity"))
    base = SearchResult(url="https://example.com/item", title="Item", engine="engine-a", category="web")
    sid = storage.add_search_result(run_id, "same query", 1, base)
    storage.add_search_result(
        run_id,
        "same query",
        2,
        base.model_copy(update={"engine": "publisher-b", "category": "news", "published_at": "2026-08-18"}),
    )
    paths = storage.source_discoveries(run_id, sid)
    assert len(paths) == 2
    assert {(p["engine"], p["category"]) for p in paths} == {("engine-a", "web"), ("publisher-b", "news")}
