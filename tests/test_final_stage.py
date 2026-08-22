from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

from traceweave.agent import PromptInterpreter
from traceweave.config import Settings
from traceweave.engine import ResearchEngine
from traceweave.exporter import Exporter
from traceweave.media import analyze_media_locally
from traceweave.models import ResearchSpec, SearchResult, TriageResult
from traceweave.planner import Planner
from traceweave.providers.router import ModelRouter
from traceweave.storage import Storage


class EmptySearch:
    name = "empty"

    async def search(self, query: str, *, limit: int, language: str):
        del query, limit, language
        return []


def test_unqualified_prompt_defaults_to_deep() -> None:
    spec = PromptInterpreter.heuristic("تحقیق کامل درباره یک شرکت")
    assert spec.mode == "deep"
    assert spec.language == "fa"


def test_preferred_model_route_retains_auto_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "providers.toml"
    config.write_text(
        """
[[providers]]
id="p"
driver="openai_compat"
base_url="https://example.invalid/v1"
[[providers.credentials]]
id="a"
token_env="KEY_A"
[[providers.models]]
id="m1"
name="model-one"
tasks=["planning"]
priority=1
[[providers.models]]
id="m2"
name="model-two"
tasks=["planning"]
priority=50
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("KEY_A", "secret")
    storage = Storage(tmp_path / "db.sqlite", tmp_path / "data")
    storage.init()
    router = ModelRouter(Settings(data_dir=tmp_path / "data", provider_config=config), storage)
    assert router._task_attempts("planning") == 4

    assert router.prefer("p:a:m2")
    assert router.primary_route("planning")["deployment_key"] == "p:a:m2"
    assert next(row for row in router.status_rows("planning") if row["preferred"])["model"] == "m2"
    assert router.prefer("auto")
    assert router.preferred_deployment is None
    assert router.primary_route("planning")["deployment_key"] == "p:a:m1"


def test_case_workspace_contains_live_report_graph_and_important_media(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db.sqlite", tmp_path / "data")
    storage.init()
    run_id = storage.create_run(ResearchSpec(topic="Case workspace", mode="deep"))
    source_id = storage.add_search_result(
        run_id,
        "case query",
        1,
        SearchResult(url="https://example.com/photo", title="Photo", engine="fixture"),
    )
    artifact_id = storage.save_artifact(
        run_id,
        b"public-image-bytes",
        media_type="image/png",
        source_id=source_id,
    )
    storage.add_observation(
        run_id,
        kind="ocr:text",
        value_text="Project Lantern",
        source_id=source_id,
        artifact_id=artifact_id,
        confidence=0.9,
        importance=91,
        rarity=84,
    )
    storage.update_run(run_id, status="completed", final_summary=f"Finding [S{source_id}]")

    case_dir = Exporter(storage, tmp_path / "cases").case(run_id)
    assert (case_dir / "report.md").is_file()
    assert (case_dir / "findings.json").is_file()
    findings = json.loads((case_dir / "findings.json").read_text(encoding="utf-8"))
    assert "queries" in findings
    assert "provider_usage" in findings
    assert (case_dir / "manifest.json").is_file()
    assert (case_dir / f"{run_id}.mmd").is_file()
    assert (case_dir / f"{run_id}.graphml").is_file()
    assert any((case_dir / "media").iterdir())


@pytest.mark.asyncio
async def test_local_media_layers_are_composed_without_remote_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("traceweave.media._perceptual_hash", lambda data: "abc123")
    monkeypatch.setattr(
        "traceweave.media._image_metrics",
        lambda data: {"width": 640, "height": 480, "edge_density": 0.12},
    )
    monkeypatch.setattr("traceweave.media.shutil.which", lambda executable: None)

    rows = await analyze_media_locally(b"image", media_type="image/png", language="fa")
    assert {row["kind"] for row in rows} == {"media:phash", "media:image_metrics"}


def test_research_state_exposes_source_language_media_and_graph_gaps(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        archives_enabled=False,
        academic_enabled=False,
        github_enabled=False,
        entity_graph_enabled=False,
        frontier_enabled=False,
    )
    settings.ensure_dirs()
    storage = Storage(settings.db_path, settings.data_dir)
    storage.init()
    run_id = storage.create_run(ResearchSpec(topic="نمونه شرکت", mode="deep", language="fa"))
    storage.add_search_result(
        run_id,
        "نمونه شرکت example company",
        1,
        SearchResult(url="https://example.com/a", category="web", engine="fixture"),
    )
    storage.complete_query(run_id, 1, "نمونه شرکت example company")
    engine = ResearchEngine(
        settings=settings,
        storage=storage,
        search=EmptySearch(),
        planner=Planner(None),
        provider=None,
    )

    state = engine._research_state(run_id)
    assert state["source_categories"] == {"web": 1}
    assert state["has_english_bridge_query"] is True
    assert state["has_non_latin_query"] is True
    assert "no literal-grounded claims passed extraction" in state["coverage_gaps"]


@pytest.mark.asyncio
async def test_slash_palette_opens_and_click_executes_help(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if importlib.util.find_spec("textual") is None:
        pytest.skip("Textual is not installed")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRACEWEAVE_DATA_DIR", str(tmp_path / "state"))
    from textual.widgets import Input, OptionList

    from traceweave.tui.app import TraceWeaveApp

    app = TraceWeaveApp()
    async with app.run_test(size=(120, 40)) as pilot:
        launch = app.query_one("#launch-input", Input)
        launch.value = "/help"
        await pilot.pause()
        palette = app.query_one("#launch-palette", OptionList)
        assert bool(palette.display)
        assert palette.option_count == 1
        await pilot.click("#launch-palette", offset=(2, 0))
        await pilot.pause()
        assert bool(app.query_one("#workspace").display)
        assert launch.value == ""


@pytest.mark.asyncio
async def test_deep_planner_runs_parallel_specialist_branches() -> None:
    class BranchProvider:
        def __init__(self) -> None:
            self.active = 0
            self.peak = 0
            self.roles: list[str] = []

        async def json(self, **kwargs):
            payload = json.loads(kwargs["user"])
            role = payload["independent_branch"]
            self.roles.append(role)
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0.01)
                return {
                    "objective": "Map independent branches",
                    "focus": [role],
                    "queries": [f"example {role}"],
                    "rationale": role,
                    "gaps": [f"gap {role}"],
                    "source_classes": ["official"],
                }
            finally:
                self.active -= 1

    provider = BranchProvider()
    plan = await Planner(provider).initial(ResearchSpec(topic="Example", mode="deep"))
    assert provider.peak == 4
    assert len(provider.roles) == 4
    assert len(plan.queries) == 4
    assert plan.rationale.startswith("Parallel specialist planning branches:")


def _observation_engine(tmp_path: Path, provider=None) -> tuple[ResearchEngine, Storage, str, int]:
    settings = Settings(
        data_dir=tmp_path / "data",
        archives_enabled=False,
        academic_enabled=False,
        github_enabled=False,
        entity_graph_enabled=False,
        frontier_enabled=False,
    )
    settings.ensure_dirs()
    storage = Storage(settings.db_path, settings.data_dir)
    storage.init()
    run_id = storage.create_run(ResearchSpec(topic="Example Robotics", mode="deep"))
    source_id = storage.add_search_result(
        run_id,
        "example robotics",
        1,
        SearchResult(url="https://example.com/lab-photo", title="Lab photo", engine="fixture"),
    )
    engine = ResearchEngine(
        settings=settings,
        storage=storage,
        search=EmptySearch(),
        planner=Planner(provider),
        provider=provider,
    )
    return engine, storage, run_id, source_id


def test_public_ocr_metadata_and_vision_become_provenance_capsules(tmp_path: Path) -> None:
    engine, storage, run_id, source_id = _observation_engine(tmp_path)
    storage.add_observation(
        run_id,
        kind="ocr:text",
        value_text="Project Lantern",
        source_id=source_id,
        locator={"page": 1, "box": [10, 20, 90, 40]},
        confidence=0.91,
        importance=88,
        rarity=95,
    )
    storage.add_observation(
        run_id,
        kind="metadata:exif",
        value_text='{"camera":"ExampleCam","captured":"2026-03-01"}',
        source_id=source_id,
        importance=2,
    )
    storage.add_observation(
        run_id,
        kind="ocr:text",
        value_text="private note",
        source_id=source_id,
        importance=99,
        sensitivity="restricted",
    )
    storage.add_observation(
        run_id,
        kind="note",
        value_text="irrelevant low-score text",
        source_id=source_id,
        importance=2,
    )

    capsules = engine._agent_observation_capsules(run_id)
    assert [row["kind"] for row in capsules] == ["ocr:text", "metadata:exif"]
    assert capsules[0]["text"] == "Project Lantern"
    assert capsules[0]["source_id"] == source_id
    assert capsules[0]["locator"] == {"page": 1, "box": [10, 20, 90, 40]}
    assert capsules[0]["observed_at"]


@pytest.mark.asyncio
async def test_replan_reserves_query_capacity_for_ocr_lead() -> None:
    capsule = {
        "kind": "ocr:text",
        "text": "Project Lantern",
        "source_id": 7,
        "artifact_id": "sha256-fixture",
        "locator": {"box": [1, 2, 3, 4]},
        "confidence": 0.84,
    }
    plan = await Planner(None).replan(
        ResearchSpec(topic="Example Robotics", mode="deep"),
        round_no=2,
        completed_queries=[],
        sources=[],
        observation_capsules=[capsule],
    )
    assert plan.queries[0] == '"Project Lantern" "Example Robotics"'


@pytest.mark.asyncio
async def test_synthesis_provider_receives_public_observation_capsules(tmp_path: Path) -> None:
    class CaptureProvider:
        def __init__(self) -> None:
            self.payload: dict | None = None

        async def json(self, **kwargs):
            self.payload = json.loads(kwargs["user"])
            return {
                "finding_groups": [],
                "observation_groups": [
                    {
                        "heading": "Visual leads",
                        "observation_ids": [self.payload["observation_capsules"][0]["id"]],
                    }
                ],
                "unresolved_questions": ["Can the visible text be corroborated"],
            }

    provider = CaptureProvider()
    engine, storage, run_id, source_id = _observation_engine(tmp_path, provider)
    storage.add_observation(
        run_id,
        kind="vision:visible_text",
        value_text="Project Lantern",
        source_id=source_id,
        locator={"frame": 3},
        confidence=0.78,
        importance=90,
        rarity=90,
    )

    report = await engine._synthesize(run_id, ResearchSpec(topic="Example Robotics", mode="deep"))
    assert provider.payload is not None
    assert "source_leads" not in provider.payload
    assert "sources" not in provider.payload
    capsule = provider.payload["observation_capsules"][0]
    assert capsule["text"] == "Project Lantern"
    assert capsule["locator"] == {"frame": 3}
    assert "Project Lantern" in report
    assert "not identity proof or corroborated facts" in report


def test_cached_search_rejects_year_only_cross_topic_matches(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "db.sqlite", tmp_path / "data")
    storage.init()
    run_id = storage.create_run(ResearchSpec(topic="Cache seed", mode="quick"))
    storage.add_search_result(
        run_id,
        "Cloudflare Workers AI 2026",
        1,
        SearchResult(
            url="https://blog.cloudflare.com/author/example",
            title="Cloudflare Workers AI updates in 2026",
            snippet="Workers AI model routing changes announced during 2026.",
            engine="fixture",
        ),
    )
    storage.add_search_result(
        run_id,
        "ソニー 画像センサー 2026",
        1,
        SearchResult(
            url="https://www.sony-semicon.example/ja/news",
            title="ソニー 画像センサー 2026 戦略",
            snippet="次世代 画像センサー の発表",
            engine="fixture",
        ),
    )

    results = storage.cached_search("ソニー 画像センサー 2025 2026 矛盾 記事")
    urls = {result.url for result in results}
    assert "https://www.sony-semicon.example/ja/news" in urls
    assert "https://blog.cloudflare.com/author/example" not in urls


def test_known_irrelevant_metadata_stays_stored_but_not_sent_to_agent(tmp_path: Path) -> None:
    engine, storage, run_id, source_id = _observation_engine(tmp_path)
    storage.save_analysis(
        run_id,
        source_id,
        TriageResult(relevance=0, importance=0, novelty=0, authority=0),
    )
    storage.add_observation(
        run_id,
        kind="page_metadata",
        value_text='{"title":"unrelated cached page"}',
        source_id=source_id,
        importance=25,
    )
    storage.add_observation(
        run_id,
        kind="ocr:text",
        value_text="Project Lantern",
        source_id=source_id,
        importance=85,
        rarity=90,
    )

    stored = storage.observations_for_run(run_id)
    capsules = engine._agent_observation_capsules(run_id)
    appendix = engine._local_evidence_appendix(run_id)
    assert {row["kind"] for row in stored} == {"page_metadata", "ocr:text"}
    assert [row["kind"] for row in capsules] == ["ocr:text"]
    assert "Project Lantern" in appendix
    assert "unrelated cached page" not in appendix


@pytest.mark.asyncio
async def test_source_analysis_uses_bounded_parallelism(tmp_path: Path) -> None:
    class SlowAnalyzer:
        def __init__(self) -> None:
            self.active = 0
            self.peak = 0

        async def triage(self, *args, **kwargs):
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0.02)
                return TriageResult(relevance=80, importance=70, novelty=60, authority=75)
            finally:
                self.active -= 1

    settings = Settings(
        data_dir=tmp_path / "data",
        archives_enabled=False,
        academic_enabled=False,
        github_enabled=False,
        entity_graph_enabled=False,
        frontier_enabled=False,
        claims_enabled=False,
        triage_enabled=True,
        research_query_concurrency=3,
    )
    settings.ensure_dirs()
    storage = Storage(settings.db_path, settings.data_dir)
    storage.init()
    run_id = storage.create_run(ResearchSpec(topic="Parallel evidence", mode="quick"))
    for index in range(4):
        source_id = storage.add_search_result(
            run_id,
            "parallel evidence",
            index + 1,
            SearchResult(url=f"https://example{index}.com/page", title=f"Source {index}"),
        )
        storage.save_snapshot(
            source_id=source_id,
            final_url=f"https://example{index}.com/page",
            status_code=200,
            content_type="text/html",
            content_hash=f"hash-{index}",
            raw=b"evidence",
            text="Parallel evidence with a literal grounded sentence.",
            extracted_title=f"Source {index}",
        )

    engine = ResearchEngine(
        settings=settings,
        storage=storage,
        search=EmptySearch(),
        planner=Planner(None),
        provider=None,
    )
    analyzer = SlowAnalyzer()
    engine.analyzer = analyzer
    await engine._analyze_new_sources(run_id, ResearchSpec(topic="Parallel evidence", mode="quick"), 1)
    assert analyzer.peak == 3
    assert len(storage.analyzed_source_ids(run_id)) == 4
