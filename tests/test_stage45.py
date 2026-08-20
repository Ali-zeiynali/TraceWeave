from __future__ import annotations

from pathlib import Path

import pytest

from traceweave.config import Settings
from traceweave.fetcher import extract_payload
from traceweave.graph import GraphCurator
from traceweave.models import ResearchSpec, SearchResult
from traceweave.providers.catalog import ModelCatalog
from traceweave.providers.config import load_provider_config
from traceweave.sources.citations import extract_citation_leads
from traceweave.storage import Storage


def _storage(tmp_path: Path) -> Storage:
    s = Storage(tmp_path / "db.sqlite", tmp_path / "data")
    s.init()
    return s


def test_builtin_provider_env_accepts_three_tokens_and_scopes_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "a")
    monkeypatch.setenv("GROQ_API_KEY_2", "b")
    monkeypatch.setenv("GROQ_API_KEY_3", "c")
    catalog_path = tmp_path / "data" / "catalog" / "models.json"
    ModelCatalog(catalog_path)
    catalog_path.write_text(
        '{"version":2,"updated_at":{},"providers":{"groq":{"token-1":[{"id":"only-a","is_free":null,"raw":{}}],"token-2":[{"id":"only-b","is_free":null,"raw":{}}],"token-3":[{"id":"only-c","is_free":null,"raw":{}}]}}}',
        encoding="utf-8",
    )
    cfg = load_provider_config(
        Settings(data_dir=tmp_path / "data", provider_config=tmp_path / "missing.toml")
    )
    groq = next(p for p in cfg.providers if p.id == "groq")
    assert [c.id for c in groq.credentials] == ["token-1", "token-2", "token-3"]
    routes = {(next(iter(m.credentials)), m.name) for m in groq.models}
    assert routes == {("token-1", "only-a"), ("token-2", "only-b"), ("token-3", "only-c")}


def test_archive_state_prevents_duplicate_done_work_but_error_is_retriable(tmp_path: Path):
    s = _storage(tmp_path)
    run = s.create_run(ResearchSpec(topic="archive"))
    sid = s.add_search_result(run, "q", 1, SearchResult(url="https://example.com", title="x"))
    assert s.source_stage_state(run, sid, "archive:wayback") is None
    s.mark_source_stage(run, sid, "archive:wayback", status="error", error="temporary")
    assert s.source_stage_state(run, sid, "archive:wayback")["status"] == "error"
    s.mark_source_stage(run, sid, "archive:wayback", status="done", result_count=2)
    row = s.source_stage_state(run, sid, "archive:wayback")
    assert row and row["status"] == "done" and row["result_count"] == 2


def test_citation_snowball_extracts_public_doi_arxiv_and_urls():
    text = "See doi:10.1000/xyz123 and arXiv:2501.01234 plus https://example.org/report.pdf."
    rows = extract_citation_leads(text)
    kinds = {r.kind for r in rows}
    assert {"doi", "arxiv", "url"}.issubset(kinds)


@pytest.mark.asyncio
async def test_graph_curator_fallback_is_claim_grounded(tmp_path: Path):
    s = _storage(tmp_path)
    run = s.create_run(ResearchSpec(topic="graph"))
    sid = s.add_search_result(run, "q", 1, SearchResult(url="https://example.com", title="x"))
    # Build the same tables through public storage methods used by EvidenceAnalyzer.
    claim_id = s.add_claim(
        run,
        sid,
        claim_text="Acme acquired Beta in 2025",
        subject="Acme",
        predicate="acquired",
        object_text="Beta",
        observed_at="2025",
        confidence=0.9,
        quote="Acme acquired Beta in 2025",
        char_start=0,
        char_end=26,
        verified_span=True,
    )
    stats = await GraphCurator(s, None).curate(run, ResearchSpec(topic="graph"))
    assert stats["entities"] >= 2 and stats["relationships"] >= 1 and stats["timeline"] >= 1
    rels = s.relationships_for_run(run)
    assert rels[0]["claim_id"] == claim_id and rels[0]["source_id"] == sid


def test_pdf_pipeline_accepts_stage4_documents():
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_metadata({"/Title": "Fixture report"})
    buf = BytesIO()
    writer.write(buf)
    text, title, links, feeds = extract_payload(
        buf.getvalue(), "application/pdf", "https://example.org/report.pdf"
    )
    assert title == "Fixture report" and links == [] and feeds == []
