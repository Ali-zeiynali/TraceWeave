from pathlib import Path

from traceweave.exporter import Exporter
from traceweave.models import Plan, ResearchSpec, SearchResult
from traceweave.storage import Storage


def test_markdown_json_and_mermaid_exports(tmp_path: Path):
    storage = Storage(tmp_path / "db.sqlite", tmp_path / "data")
    storage.init()
    run_id = storage.create_run(ResearchSpec(topic="Export Example"))
    storage.save_plan(run_id, 1, Plan(objective="map", queries=["export query"]))
    sid = storage.add_search_result(
        run_id, "export query", 1,
        SearchResult(url="https://example.com/a", title="Example source", engine="fixture"),
    )
    storage.complete_query(run_id, 1, "export query")
    storage.update_run(run_id, current_round=1, status="completed", final_summary=f"Evidence [S{sid}]")
    exporter = Exporter(storage, tmp_path / "exports")
    md = exporter.markdown(run_id).read_text(encoding="utf-8")
    js = exporter.json(run_id).read_text(encoding="utf-8")
    mmd = exporter.mermaid(run_id).read_text(encoding="utf-8")
    assert "Discovery paths" in md
    assert '"discoveries"' in js
    assert "flowchart TD" in mmd and "export query" in mmd
