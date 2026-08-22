from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from importlib.resources import files
from math import ceil

from traceweave.agent import PromptInterpreter
from traceweave.analysis import EvidenceAnalyzer
from traceweave.config import Settings
from traceweave.exporter import Exporter
from traceweave.fetcher import (
    BrowserFetcher,
    CloudflareBrowserFetcher,
    FetchError,
    FetchResult,
    SafeFetcher,
)
from traceweave.frontier import FrontierManager
from traceweave.graph import GraphCurator
from traceweave.identity import IdentityResolver
from traceweave.media import analyze_media_locally
from traceweave.models import ProgressEvent, ResearchSpec, SourceView
from traceweave.planner import Planner
from traceweave.providers.base import LLMError, LLMProvider
from traceweave.search.base import SearchBackend, SearchError
from traceweave.skills import SkillRegistry
from traceweave.sources.manager import SpecialistManager
from traceweave.storage import Storage
from traceweave.utils import lexical_overlap, metadata_published_at
from traceweave.verification import ClaimVerifier

ProgressCallback = Callable[[ProgressEvent], Awaitable[None] | None]


class ResearchEngine:
    def __init__(
        self,
        *,
        settings: Settings,
        storage: Storage,
        search: SearchBackend,
        planner: Planner,
        provider: LLMProvider | None,
        callback: ProgressCallback | None = None,
    ):
        self.settings = settings
        self.storage = storage
        self.search = search
        self.planner = planner
        self.provider = provider
        self.callback = callback
        self.fetcher = SafeFetcher(
            timeout=settings.fetch_timeout_seconds,
            max_bytes=settings.fetch_max_bytes,
            user_agent=settings.user_agent,
            per_host_delay=settings.fetch_per_host_delay_seconds,
            retries=settings.fetch_retries,
        )
        self.browser = BrowserFetcher(
            timeout=settings.fetch_timeout_seconds * 1.5, max_bytes=settings.fetch_max_bytes
        )
        cloudflare_credentials: list[tuple[str, str]] = []
        for idx in range(1, 4):
            suffix = "" if idx == 1 else f"_{idx}"
            account = os.getenv(f"CLOUDFLARE_ACCOUNT_ID{suffix}", "").strip()
            token = os.getenv(f"CLOUDFLARE_API_KEY{suffix}", "").strip()
            if account and token:
                cloudflare_credentials.append((account, token))
        self.cloudflare_browser = CloudflareBrowserFetcher(
            cloudflare_credentials,
            timeout=settings.fetch_timeout_seconds * 2.5,
            max_bytes=settings.fetch_max_bytes,
        )
        self.frontier = FrontierManager(
            storage, self.fetcher, user_agent=settings.user_agent, respect_robots=settings.respect_robots
        )
        self.analyzer = EvidenceAnalyzer(storage, provider)
        self.specialists = SpecialistManager(settings, storage, self.fetcher)
        self.graph = GraphCurator(storage, provider)
        self.identity = IdentityResolver(storage, provider)
        self.verifier = ClaimVerifier(storage, provider)
        self.skills = SkillRegistry()
        self.interpreter = PromptInterpreter(provider)
        self._fetch_sem = asyncio.Semaphore(settings.fetch_concurrency)

    async def _emit(self, run_id: str | None, kind: str, message: str, **data) -> None:
        self.storage.event(run_id, kind, message, data)
        if run_id and kind in {
            "plan.ready",
            "round.completed",
            "vision.completed",
            "run.completed",
            "run.failed",
            "run.paused",
        }:
            try:
                Exporter(self.storage, self.settings.data_dir / "cases").case(run_id)
            except (OSError, KeyError, ValueError) as exc:
                self.storage.event(run_id, "case.refresh_failed", f"Case workspace refresh failed: {exc}")
        if self.callback:
            try:
                result = self.callback(ProgressEvent(kind=kind, message=message, data=data))
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                self.storage.event(
                    run_id,
                    "callback.failed",
                    f"Progress callback failed: {type(exc).__name__}",
                    {"source_event": kind},
                )

    async def start(self, spec: ResearchSpec) -> str:
        run_id = self.storage.create_run(spec)
        await self._emit(run_id, "run.created", f"Created research run {run_id}", topic=spec.topic)
        return await self.resume(run_id)

    async def start_prompt(self, prompt: str, *, defaults: ResearchSpec | None = None) -> str:
        spec = await self.interpreter.resolve(prompt, defaults=defaults)
        return await self.start(spec)

    async def resume(self, run_id: str) -> str:
        row = self.storage.get_run(run_id)
        if not row:
            raise KeyError(f"Unknown run: {run_id}")
        spec = self.storage.run_spec(run_id)
        recovered = self.storage.recover_frontier_leases(run_id)
        recovered_tasks = self.storage.recover_expired_tasks(run_id)
        if recovered:
            await self._emit(run_id, "frontier.recovered", f"Recovered {recovered} leased frontier tasks")
        if recovered_tasks:
            await self._emit(run_id, "tasks.recovered", f"Recovered {recovered_tasks} expired task leases")
        self.storage.update_run(run_id, status="running", last_error=None)
        await self._emit(run_id, "run.started", f"Research started/resumed: {spec.topic}")
        try:
            previous_task: str | None = None
            completed_round = int(row["current_round"])
            for task in self.storage.tasks_for_run(run_id):
                if task["kind"] == "research_round" and task["state"] == "completed":
                    previous_task = str(task["id"])
            for round_no in range(int(row["current_round"]) + 1, spec.resolved_rounds() + 1):
                if self._deadline_reached(run_id):
                    await self._emit(
                        run_id,
                        "run.deadline_reached",
                        "Deadline reached; producing a partial report",
                    )
                    break
                task_id = self.storage.enqueue_task(
                    run_id,
                    "research_round",
                    {"round": round_no},
                    dedupe_key=f"round:{round_no}",
                    priority=round_no,
                    max_attempts=3,
                    depends_on=[previous_task] if previous_task else None,
                )
                existing = next(task for task in self.storage.tasks_for_run(run_id) if task["id"] == task_id)
                if existing["state"] == "completed":
                    completed_round = round_no
                    previous_task = task_id
                    continue
                leased = self.storage.lease_tasks(
                    run_id,
                    f"engine-{run_id}",
                    kinds={"research_round"},
                    limit=1,
                    lease_seconds=max(300, ceil(self.settings.llm_timeout_seconds) * 20),
                )
                if not leased or leased[0]["id"] != task_id:
                    raise RuntimeError(f"Round {round_no} is blocked by an unfinished durable task")
                try:
                    await self._run_round(run_id, spec, round_no)
                    self.storage.complete_task(task_id, {"round": round_no})
                except asyncio.CancelledError:
                    self.storage.release_task(task_id)
                    raise
                except Exception as exc:
                    self.storage.fail_task(task_id, str(exc))
                    raise
                completed_round = round_no
                previous_task = task_id
                self.storage.update_run(run_id, current_round=round_no)
                await self._emit(
                    run_id,
                    "round.completed",
                    f"Completed round {round_no}/{spec.resolved_rounds()}",
                    round=round_no,
                )
            if completed_round > int(row["current_round"]):
                self.storage.update_run(run_id, current_round=completed_round)
            summary = await self._synthesize(run_id, spec)
            self.storage.update_run(run_id, status="completed", final_summary=summary)
            await self._emit(
                run_id,
                "run.completed",
                "Research completed",
                source_count=len(self.storage.sources_for_run(run_id, 5000)),
                claim_count=len(self.storage.claims_for_run(run_id, 5000)),
                frontier=self.storage.frontier_stats(run_id),
            )
            return run_id
        except asyncio.CancelledError:
            self.storage.update_run(run_id, status="paused")
            await self._emit(run_id, "run.paused", "Research paused and can be resumed")
            raise
        except Exception as exc:
            self.storage.update_run(run_id, status="failed", last_error=str(exc))
            await self._emit(run_id, "run.failed", f"Research failed: {exc}")
            raise

    def _deadline_reached(self, run_id: str) -> bool:
        row = self.storage.get_run(run_id) or {}
        value = row.get("deadline_at")
        if not value:
            return False
        try:
            return datetime.now(UTC) >= datetime.fromisoformat(str(value)).astimezone(UTC)
        except ValueError:
            return False

    async def _run_round(self, run_id: str, spec: ResearchSpec, round_no: int) -> None:
        plan = self.storage.get_plan(run_id, round_no)
        if plan is None:
            if round_no == 1:
                plan = await self.planner.initial(spec, run_id=run_id)
            else:
                plan = await self.planner.replan(
                    spec,
                    round_no=round_no,
                    completed_queries=self.storage.completed_queries(run_id),
                    sources=self.storage.sources_for_run(run_id, limit=60),
                    claims=self.storage.claims_for_run(run_id, 80),
                    research_state=self._research_state(run_id),
                    observation_capsules=self._agent_observation_capsules(run_id),
                    run_id=run_id,
                )
            self.storage.save_plan(run_id, round_no, plan)
        await self._emit(
            run_id,
            "plan.ready",
            f"Round {round_no} plan: {plan.objective}",
            round=round_no,
            objective=plan.objective,
            focus=plan.focus,
            queries=plan.queries,
            gaps=plan.gaps,
            source_classes=plan.source_classes,
        )

        pending_queries = self.storage.pending_queries(run_id, round_no)
        if self._deadline_reached(run_id):
            await self._emit(
                run_id,
                "round.deadline_reached",
                f"Deadline reached during round {round_no}; remaining work stays resumable",
                round=round_no,
            )
            return
        branch_sem = asyncio.Semaphore(self.settings.research_query_concurrency)

        async def search_branch(query: str) -> None:
            async with branch_sem:
                await self._search_query(run_id, spec, round_no, query)

        await asyncio.gather(*(search_branch(query) for query in pending_queries))

        # Stage 4: specialist sources are independent from generic search and may fail without killing the run.
        specialist = await self.specialists.discover(run_id, spec, plan, round_no)
        for warning in specialist.errors or []:
            await self._emit(run_id, "specialist.failed", warning, round=round_no)
        if specialist.academic or specialist.code or specialist.registries or specialist.social:
            await self._emit(
                run_id,
                "specialists.discovered",
                "Specialist discovery: "
                f"academic={specialist.academic} code={specialist.code} "
                f"registries={specialist.registries} social={specialist.social}",
                academic=specialist.academic,
                code=specialist.code,
                registries=specialist.registries,
                social=specialist.social,
                round=round_no,
            )
            await self._fetch_specialist_sources(run_id, spec)

        await self._analyze_new_sources(run_id, spec, round_no)
        if self.settings.media_enabled and spec.mode in {"deep", "overnight"}:
            await self._collect_media(run_id, spec, round_no)
        if self.settings.archives_enabled and spec.mode != "quick":
            archive_count = await self.specialists.archive_top_sources(run_id, spec)
            if archive_count:
                await self._emit(
                    run_id,
                    "archives.discovered",
                    f"Discovered {archive_count} historical captures",
                    count=archive_count,
                    round=round_no,
                )
                await self._fetch_specialist_sources(run_id, spec, categories={"archive"})
                await self._analyze_new_sources(run_id, spec, round_no)
                if self.settings.media_enabled and spec.mode in {"deep", "overnight"}:
                    await self._collect_media(run_id, spec, round_no)
        if (
            self.settings.frontier_enabled
            and spec.resolved_frontier_pages() > 0
            and spec.resolved_depth() > 0
        ):
            await self._crawl_frontier(run_id, spec, round_no)
            await self._analyze_new_sources(run_id, spec, round_no)

        if self.settings.entity_graph_enabled:
            graph_stats = await self.graph.curate(run_id, spec)
            await self._emit(
                run_id,
                "graph.curated",
                f"Graph: entities={graph_stats['entities']} relationships={graph_stats['relationships']} timeline={graph_stats['timeline']}",
                **graph_stats,
                round=round_no,
            )

        verification = await self.verifier.assess(run_id, spec)
        if verification:
            await self._emit(
                run_id,
                "claims.verified",
                "Claim assessment: "
                + ", ".join(f"{key}={value}" for key, value in sorted(verification.items())),
                verdicts=verification,
                round=round_no,
            )

        identity = await self.identity.resolve(run_id, spec)
        if identity["identity_hypotheses"] or identity["media_matches"]:
            await self._emit(run_id, "identity.assessed", "Identity candidates were assessed", **identity)

        coverage = self._research_state(run_id)
        await self._emit(
            run_id,
            "coverage.audit",
            f"Coverage audit: domains={coverage['distinct_domains']} gaps={len(coverage['coverage_gaps'])}",
            state=coverage,
            round=round_no,
        )

    def _research_state(self, run_id: str) -> dict[str, object]:
        sources = self.storage.sources_for_run(run_id, 5000)
        observations = self.storage.observations_for_run(run_id, 5000)
        queries = self.storage.completed_queries(run_id)
        if not queries:
            queries = list(dict.fromkeys(source.search_query for source in sources if source.search_query))
        claims = self.storage.claims_for_run(run_id, 5000)
        assessments = self.storage.claim_assessments_for_run(run_id, 5000)
        media_leads = self.storage.media_leads_for_run(run_id, 5000)
        source_categories: dict[str, int] = {}
        for source in sources:
            key = source.category or "unknown"
            source_categories[key] = source_categories.get(key, 0) + 1
        observation_kinds: dict[str, int] = {}
        for observation in observations:
            key = str(observation.get("kind") or "unknown")
            observation_kinds[key] = observation_kinds.get(key, 0) + 1
        gaps: list[str] = []
        domains = {source.domain for source in sources if source.domain}
        if sources and len(domains) < 3:
            gaps.append("fewer than three independent source domains")
        if not claims:
            gaps.append("no literal-grounded claims passed extraction")
        if media_leads and not observations:
            gaps.append("media was discovered but has no OCR/metadata/vision observations")
        entities = self.storage.entities_for_run(run_id, 5000)
        relationships = self.storage.relationships_for_run(run_id, 5000)
        if entities and not relationships:
            gaps.append("entities exist but no relationships have been grounded")

        return {
            "archive_captures": len(self.storage.archive_captures_for_run(run_id, 5000)),
            "citations": len(self.storage.citations_for_run(run_id, 5000)),
            "entities": len(entities),
            "relationships": len(relationships),
            "timeline_events": len(self.storage.timeline_for_run(run_id, 5000)),
            "frontier": self.storage.frontier_stats(run_id),
            "media_leads": len(media_leads),
            "artifacts": len(self.storage.artifacts_for_run(run_id, 5000)),
            "observations": len(observations),
            "source_categories": source_categories,
            "observation_kinds": observation_kinds,
            "distinct_domains": len(domains),
            "completed_queries": len(queries),
            "has_english_bridge_query": any(any("a" <= c.casefold() <= "z" for c in q) for q in queries),
            "has_non_latin_query": any(any(ord(c) > 127 for c in q) for q in queries),
            "verified_claims": sum(bool(claim.get("verified_span")) for claim in claims),
            "claim_verdicts": {
                verdict: sum(1 for item in assessments if item["verdict"] == verdict)
                for verdict in ("corroborated", "single_source", "contested", "insufficient")
            },
            "identity_hypotheses": len(self.storage.identity_hypotheses_for_run(run_id, 5000)),
            "media_matches": len(self.storage.artifact_matches_for_run(run_id, 5000)),
            "unfetched_sources": sum(not source.fetched for source in sources),
            "coverage_gaps": gaps,
        }

    def _reportable_observations(self, run_id: str, limit: int = 80) -> list[dict]:
        """Keep raw observations stored while excluding known-irrelevant metadata from reports."""
        reportable: list[dict] = []
        for observation in self.storage.observations_for_run(run_id, limit):
            if str(observation.get("sensitivity") or "public") != "public":
                continue
            kind = str(observation.get("kind") or "unknown")
            metadata_kind = kind in {"page_metadata", "metadata", "metadata:page"}
            if metadata_kind:
                continue
            reportable.append(observation)
        return reportable

    def _agent_observation_capsules(self, run_id: str) -> list[dict[str, object]]:
        capsules: list[dict[str, object]] = []
        for observation in self._reportable_observations(run_id, 80):
            importance = float(observation.get("importance") or 0)
            kind = str(observation.get("kind") or "unknown")
            if importance < 15 and not kind.startswith(("ocr:", "vision:", "metadata:")):
                continue
            locator = observation.get("locator_json") or {}
            if isinstance(locator, str):
                try:
                    locator = json.loads(locator)
                except json.JSONDecodeError:
                    locator = {"raw": locator[:500]}
            capsules.append(
                {
                    "id": observation["id"],
                    "source_id": observation.get("source_id"),
                    "artifact_id": observation.get("artifact_id"),
                    "kind": kind,
                    "text": " ".join(str(observation.get("value_text") or "").split())[:1200],
                    "locator": locator,
                    "observed_at": observation.get("created_at"),
                    "confidence": observation.get("confidence"),
                    "importance": importance,
                    "rarity": observation.get("rarity"),
                }
            )
            if len(capsules) >= 40:
                break
        return capsules

    async def _search_query(self, run_id: str, spec: ResearchSpec, round_no: int, query: str) -> None:
        await self._emit(run_id, "search.started", f"Searching: {query}", query=query, round=round_no)
        try:
            results = await self.search.search(
                query, limit=spec.max_results_per_query, language=spec.language
            )
        except SearchError as exc:
            results = self.storage.cached_search(query, limit=spec.max_results_per_query)
            if results:
                await self._emit(
                    run_id,
                    "search.cache_fallback",
                    f"Live search failed; reused {len(results)} cached public results for: {query}",
                    query=query,
                    count=len(results),
                    error=str(exc),
                )
            else:
                self.storage.complete_query(run_id, round_no, query, error=str(exc))
                await self._emit(run_id, "search.failed", f"Search failed: {query}: {exc}", query=query)
                return
        fetch_jobs: list[tuple[int, str]] = []
        for rank, result in enumerate(results, start=1):
            source_id = self.storage.add_search_result(run_id, query, rank, result)
            self.storage.add_research_edge(
                run_id,
                from_type="query",
                from_id=query,
                relation="discovered",
                to_type="source",
                to_id=source_id,
                metadata={
                    "round": round_no,
                    "rank": rank,
                    "engine": result.engine,
                    "category": result.category,
                },
            )
            await self._emit(
                run_id,
                "source.discovered",
                result.title or result.url,
                source_id=source_id,
                url=result.url,
                title=result.title,
                engine=result.engine,
                category=result.category,
                published_at=result.published_at,
                query=query,
                rank=rank,
            )
            if rank <= spec.fetch_top_per_query and self.storage.latest_snapshot(source_id) is None:
                fetch_jobs.append((source_id, result.url))
        if fetch_jobs:
            await asyncio.gather(
                *(self._fetch_source(run_id, spec, sid, url, depth=0) for sid, url in fetch_jobs)
            )
        self.storage.complete_query(run_id, round_no, query)
        await self._emit(
            run_id, "search.completed", f"Search completed: {query}", query=query, count=len(results)
        )

    async def _fetch_source(
        self, run_id: str, spec: ResearchSpec, source_id: int, url: str, *, depth: int
    ) -> FetchResult | None:
        async with self._fetch_sem:
            if self.settings.respect_robots and not await self.frontier.allowed(url):
                await self._emit(
                    run_id,
                    "source.robots_blocked",
                    f"robots.txt disallows S{source_id}",
                    source_id=source_id,
                    url=url,
                )
                return None
            try:
                max_bytes = (
                    self.settings.pdf_max_bytes
                    if self.settings.pdf_enabled and url.casefold().split("?", 1)[0].endswith(".pdf")
                    else None
                )
                result = await self.fetcher.fetch(url, max_bytes=max_bytes)
                if (
                    self.settings.browser_fallback
                    and "html" in result.content_type.casefold()
                    and len(result.text) < self.settings.browser_min_text_chars
                ):
                    try:
                        browser_result = await self._browser_fetch(url)
                        if len(browser_result.text) > len(result.text):
                            result = browser_result
                            await self._emit(
                                run_id,
                                "source.browser_fallback",
                                f"Browser fallback improved S{source_id}",
                                source_id=source_id,
                            )
                    except FetchError as exc:
                        await self._emit(
                            run_id,
                            "source.browser_failed",
                            f"Browser fallback failed for S{source_id}: {exc}",
                            source_id=source_id,
                        )
                self.storage.save_snapshot(
                    source_id=source_id,
                    final_url=result.final_url,
                    status_code=result.status_code,
                    content_type=result.content_type,
                    content_hash=result.content_hash,
                    raw=result.raw,
                    text=result.text,
                    extracted_title=result.title,
                    simhash=result.simhash,
                )
                snapshot = self.storage.latest_snapshot(source_id) or {}
                snapshot_id = int(snapshot["id"]) if snapshot.get("id") is not None else None
                if result.metadata and snapshot_id is not None:
                    self.storage.set_run_source_published_at(
                        run_id, source_id, metadata_published_at(result.metadata)
                    )
                    self.storage.add_observation(
                        run_id,
                        kind="page_metadata",
                        value_text=json.dumps(result.metadata, ensure_ascii=False, default=str)[:12000],
                        source_id=source_id,
                        snapshot_id=snapshot_id,
                        locator={"url": result.final_url},
                        confidence=0.9,
                        importance=25,
                        rarity=15,
                    )
                for media in result.media:
                    self.storage.add_media_lead(
                        run_id,
                        source_id,
                        url=media.url,
                        kind=media.kind,
                        alt_text=media.alt,
                        width=media.width,
                        height=media.height,
                    )
                citation_added = 0
                if spec.resolved_depth() > 0 and result.text:
                    citation_added = self.specialists.snowball_citations(
                        run_id, spec, source_id, result.text, depth=min(depth + 1, spec.resolved_depth())
                    )
                added = 0
                if depth < spec.resolved_depth():
                    added = self.frontier.add_page_links(
                        run_id,
                        spec,
                        source_id=source_id,
                        parent_url=result.final_url,
                        links=result.links,
                        depth=depth + 1,
                    )
                    for feed in result.feeds:
                        self.storage.add_frontier(
                            run_id,
                            feed,
                            parent_source_id=source_id,
                            anchor="feed",
                            relation="feed",
                            depth=min(depth + 1, spec.resolved_depth()),
                            score=0.45,
                        )
                    if self.settings.sitemap_enabled:
                        sitemap_added = await self.frontier.discover_domain(
                            run_id, spec, source_id, result.final_url
                        )
                        added += sitemap_added
                await self._emit(
                    run_id,
                    "source.fetched",
                    f"Fetched source S{source_id}",
                    source_id=source_id,
                    url=result.final_url,
                    bytes=len(result.raw),
                    content_type=result.content_type,
                    links_added=added,
                    citations_added=citation_added,
                    depth=depth,
                )
                return result
            except FetchError as exc:
                await self._emit(
                    run_id,
                    "source.fetch_failed",
                    f"Could not fetch S{source_id}: {exc}",
                    source_id=source_id,
                    url=url,
                )
                return None

    async def _browser_fetch(self, url: str) -> FetchResult:
        if self.settings.browser_backend in {"cloudflare", "auto"} and self.cloudflare_browser.credentials:
            try:
                return await self.cloudflare_browser.fetch(url)
            except FetchError:
                if self.settings.browser_backend == "cloudflare":
                    raise
        return await self.browser.fetch(url)

    async def _collect_media(self, run_id: str, spec: ResearchSpec, round_no: int) -> None:
        del spec
        sources = [source for source in self.storage.sources_for_run(run_id, 100) if source.fetched]
        source_ids = [source.id for source in sources[: self.settings.media_sources_per_round]]
        leads = self.storage.pending_media_leads(
            run_id,
            source_ids=source_ids,
            per_source=self.settings.media_assets_per_source,
        )
        if not leads:
            return

        async def collect(lead: dict) -> None:
            lead_id = int(lead["id"])
            source_id = int(lead["source_id"])
            try:
                result = await self.fetcher.fetch_binary(
                    str(lead["url"]), max_bytes=self.settings.media_max_bytes
                )
                snapshot = self.storage.latest_snapshot(source_id) or {}
                analysis = self.storage.analysis_for_source(run_id, source_id) or {}
                snapshot_id = int(snapshot["id"]) if snapshot.get("id") is not None else None
                artifact_id = self.storage.save_artifact(
                    run_id,
                    result.raw,
                    media_type=result.content_type,
                    source_id=source_id,
                    snapshot_id=snapshot_id,
                    metadata={
                        "original_url": lead["url"],
                        "final_url": result.final_url,
                        "alt_text": lead.get("alt_text") or "",
                        "width": lead.get("width"),
                        "height": lead.get("height"),
                    },
                )
                self.storage.add_observation(
                    run_id,
                    kind="media_asset",
                    value_text=str(lead.get("alt_text") or result.final_url),
                    source_id=source_id,
                    snapshot_id=snapshot_id,
                    artifact_id=artifact_id,
                    locator={
                        "url": result.final_url,
                        "width": lead.get("width"),
                        "height": lead.get("height"),
                    },
                    confidence=1.0,
                    importance=float(analysis.get("importance") or 0),
                    rarity=float(analysis.get("novelty") or 0),
                )
                await self._analyze_media_artifact(
                    run_id,
                    artifact_id=artifact_id,
                    source_id=source_id,
                    snapshot_id=snapshot_id,
                    media_type=result.content_type,
                    image=result.raw,
                    alt_text=str(lead.get("alt_text") or ""),
                )
                self.storage.complete_media_lead(lead_id, artifact_id=artifact_id)
                await self._emit(
                    run_id,
                    "media.stored",
                    f"Stored media artifact {artifact_id} from S{source_id}",
                    source_id=source_id,
                    artifact_id=artifact_id,
                    media_lead_id=lead_id,
                    round=round_no,
                )
            except FetchError as exc:
                self.storage.complete_media_lead(lead_id, error=str(exc))
                await self._emit(
                    run_id,
                    "media.failed",
                    f"Media fetch failed for S{source_id}: {exc}",
                    source_id=source_id,
                    media_lead_id=lead_id,
                    round=round_no,
                )

        await asyncio.gather(*(collect(lead) for lead in leads))

    async def _analyze_media_artifact(
        self,
        run_id: str,
        *,
        artifact_id: str,
        source_id: int,
        snapshot_id: int | None,
        media_type: str,
        image: bytes,
        alt_text: str,
    ) -> None:
        run = self.storage.get_run(run_id) or {}
        if not self.storage.artifact_has_local_media_observations(artifact_id):
            local_observations = await analyze_media_locally(
                image,
                media_type=media_type,
                language=str(run.get("language") or "all"),
            )
            for item in local_observations:
                self.storage.add_observation(
                    run_id,
                    kind=str(item["kind"]),
                    value_text=str(item["text"]),
                    source_id=source_id,
                    snapshot_id=snapshot_id,
                    artifact_id=artifact_id,
                    locator=dict(item.get("locator") or {}),
                    confidence=float(item.get("confidence") or 0.5),
                    importance=float(item.get("importance") or 0),
                    rarity=float(item.get("rarity") or 0),
                )
            if local_observations:
                await self._emit(
                    run_id,
                    "local_media.completed",
                    f"Stored {len(local_observations)} deterministic media observations for {artifact_id}",
                    artifact_id=artifact_id,
                    source_id=source_id,
                    observations=len(local_observations),
                    kinds=[str(item["kind"]) for item in local_observations],
                )
        if (
            self.provider is None
            or not self.settings.remote_vision_enabled
            or not bool(run.get("allow_remote_vision"))
            or int(run.get("max_vision_calls") or 0) <= 0
            or self.storage.artifact_has_vision_observations(artifact_id)
        ):
            return
        system = files("traceweave.prompts").joinpath("vision.txt").read_text(encoding="utf-8")
        user = json.dumps(
            {
                "research_goal": run.get("topic", ""),
                "angle": run.get("angle", ""),
                "source_id": source_id,
                "artifact_id": artifact_id,
                "page_alt_text": alt_text,
            },
            ensure_ascii=False,
        )
        try:
            payload = await self.provider.vision_json(
                system=system,
                user=user,
                image=image,
                media_type=media_type,
                run_id=run_id,
            )
            saved = 0
            for item in payload.get("observations", [])[:30]:
                text = " ".join(str(item.get("text") or "").split())[:2000]
                if not text:
                    continue
                bbox = item.get("bbox")
                try:
                    box = [min(1.0, max(0.0, float(value))) for value in bbox]
                    if len(box) != 4:
                        continue
                    confidence = min(1.0, max(0.0, float(item.get("confidence", 0.5))))
                    importance = min(100.0, max(0.0, float(item.get("importance", 0))))
                    rarity = min(100.0, max(0.0, float(item.get("rarity", 0))))
                except (TypeError, ValueError):
                    continue
                kind = str(item.get("kind") or "other")[:40]
                self.storage.add_observation(
                    run_id,
                    kind=f"vision:{kind}",
                    value_text=text,
                    source_id=source_id,
                    snapshot_id=snapshot_id,
                    artifact_id=artifact_id,
                    locator={"bbox": box, "coordinate_space": "normalized"},
                    confidence=confidence,
                    importance=importance,
                    rarity=rarity,
                )
                saved += 1
            await self._emit(
                run_id,
                "vision.completed",
                f"Stored {saved} region-level observations for {artifact_id}",
                artifact_id=artifact_id,
                source_id=source_id,
                observations=saved,
            )
        except LLMError as exc:
            await self._emit(
                run_id,
                "vision.failed",
                f"Remote vision unavailable for {artifact_id}: {exc}",
                artifact_id=artifact_id,
                source_id=source_id,
            )

    async def _fetch_specialist_sources(
        self, run_id: str, spec: ResearchSpec, categories: set[str] | None = None
    ) -> None:
        categories = categories or {
            "academic",
            "code",
            "archive",
            "registry",
            "person-registry",
            "network-registry",
            "public-social",
            "news-index",
            "reference",
            "community-index",
        }
        jobs: list[tuple[int, str]] = []
        for source in self.storage.sources_for_run(run_id, 250):
            if source.category not in categories or self.storage.latest_snapshot(source.id) is not None:
                continue
            if not source.url.startswith(("http://", "https://")):
                continue
            jobs.append((source.id, source.url))
            if len(jobs) >= max(4, self.settings.specialist_results_per_query * 3):
                break
        if jobs:
            await asyncio.gather(*(self._fetch_source(run_id, spec, sid, url, depth=0) for sid, url in jobs))

    async def _crawl_frontier(self, run_id: str, spec: ResearchSpec, round_no: int) -> None:
        stats = self.storage.frontier_stats(run_id)
        completed = stats.get("completed", 0)
        total_budget = spec.resolved_frontier_pages()
        remaining = max(0, total_budget - completed)
        if remaining <= 0:
            return
        round_share = max(1, ceil(total_budget / max(1, spec.resolved_rounds())))
        round_budget = min(remaining, round_share)
        processed = 0
        await self._emit(
            run_id, "frontier.started", f"Best-first frontier crawl budget: {round_budget}", round=round_no
        )
        while processed < round_budget:
            items = self.storage.lease_frontier(
                run_id,
                max_depth=spec.resolved_depth(),
                min_score=self.settings.frontier_min_score,
                per_domain_limit=self.settings.frontier_per_domain_limit,
                limit=min(self.settings.fetch_concurrency, round_budget - processed),
            )
            if not items:
                break
            for item in items:
                processed += 1
                url = str(item["url"])
                if self.settings.respect_robots and not await self.frontier.allowed(url):
                    self.storage.complete_frontier(int(item["id"]), error="robots.txt disallow")
                    await self._emit(run_id, "frontier.blocked", f"robots.txt blocked {url}", url=url)
                    continue
                source_id = self.storage.attach_crawled_source(
                    run_id,
                    url,
                    int(item["parent_source_id"]) if item["parent_source_id"] is not None else None,
                    relation=str(item["relation"]),
                )
                await self._emit(
                    run_id,
                    "frontier.visit",
                    f"Crawling S{source_id} score={float(item['score']):.2f}",
                    source_id=source_id,
                    url=url,
                    depth=item["depth"],
                    score=item["score"],
                    relation=item["relation"],
                )
                if self.storage.latest_snapshot(source_id) is None:
                    result = await self._fetch_source(run_id, spec, source_id, url, depth=int(item["depth"]))
                    self.storage.complete_frontier(int(item["id"]), error=None if result else "fetch failed")
                else:
                    self.storage.complete_frontier(int(item["id"]))
        await self._emit(
            run_id,
            "frontier.completed",
            f"Frontier processed {processed} pages",
            processed=processed,
            stats=self.storage.frontier_stats(run_id),
        )

    async def _analyze_new_sources(self, run_id: str, spec: ResearchSpec, round_no: int) -> None:
        if not self.settings.triage_enabled:
            return
        analyzed = self.storage.analyzed_source_ids(run_id)
        sources = self.storage.sources_for_run(run_id, limit=500)
        pending_all = [s for s in sources if s.id not in analyzed]
        pending = self._prioritize_sources(spec, pending_all)
        if not pending:
            return
        if len(pending_all) > len(pending):
            await self._emit(
                run_id,
                "triage.budgeted",
                f"Selected {len(pending)} of {len(pending_all)} unreviewed sources for {spec.mode} triage",
                selected=len(pending),
                deferred=len(pending_all) - len(pending),
                mode=spec.mode,
                round=round_no,
            )
        mode_claim_cap = {"quick": 3, "standard": 6, "deep": 12, "overnight": 20}[spec.mode]
        claims_budget = min(self.settings.claims_max_sources_per_round, mode_claim_cap)
        claims_used = 0
        claims_lock = asyncio.Lock()
        analysis_sem = asyncio.Semaphore(self.settings.research_query_concurrency)

        async def analyze_source(source: SourceView) -> None:
            nonlocal claims_used
            async with analysis_sem:
                full_text = self.storage.snapshot_text(source.id)
                source_for_model = source.model_copy(
                    update={"text_excerpt": full_text[:16000] if full_text else source.text_excerpt}
                )
                snapshot = self.storage.latest_snapshot(source.id)
                duplicate_of = None
                family_key = f"domain:{source.domain}"
                if snapshot and snapshot.get("simhash"):
                    duplicate_of = self.storage.find_near_duplicate(
                        run_id, source.id, str(snapshot["simhash"]), max_distance=3
                    )
                    family_key = (
                        f"source:{duplicate_of}" if duplicate_of else f"sim:{str(snapshot['simhash'])[:12]}"
                    )
                result = await self.analyzer.triage(run_id, spec, source_for_model, sources)
                if duplicate_of:
                    result = result.model_copy(update={"novelty": min(result.novelty, 12.0)})
                self.storage.save_analysis(
                    run_id, source.id, result, family_key=family_key, duplicate_of=duplicate_of
                )
                await self._emit(
                    run_id,
                    "source.triaged",
                    f"S{source.id} R{result.relevance:.0f} I{result.importance:.0f} N{result.novelty:.0f}",
                    source_id=source.id,
                    relevance=result.relevance,
                    importance=result.importance,
                    novelty=result.novelty,
                    authority=result.authority,
                    duplicate_of=duplicate_of,
                    leads=result.leads,
                    round=round_no,
                )
                eligible = (
                    self.settings.claims_enabled
                    and self.provider is not None
                    and bool(full_text)
                    and not duplicate_of
                    and result.relevance >= self.settings.claim_min_relevance
                )
                extract = False
                if eligible:
                    async with claims_lock:
                        if claims_used < claims_budget:
                            claims_used += 1
                            extract = True
                if not extract:
                    return
                claims = await self.analyzer.extract_claims(run_id, spec, source_for_model)
                for claim in claims:
                    start = full_text.find(claim.evidence_quote)
                    if start < 0:
                        continue
                    claim_id = self.storage.add_claim(
                        run_id,
                        source.id,
                        claim_text=claim.claim,
                        subject=claim.subject,
                        predicate=claim.predicate,
                        object_text=claim.object,
                        observed_at=claim.observed_at,
                        confidence=claim.confidence,
                        quote=claim.evidence_quote,
                        char_start=start,
                        char_end=start + len(claim.evidence_quote),
                        verified_span=True,
                        importance=result.importance,
                        rarity=result.novelty,
                    )
                    await self._emit(
                        run_id,
                        "claim.extracted",
                        f"C{claim_id} from S{source.id}: {claim.claim[:120]}",
                        claim_id=claim_id,
                        source_id=source.id,
                    )

        await asyncio.gather(*(analyze_source(source) for source in pending))

    @staticmethod
    def _prioritize_sources(spec: ResearchSpec, sources: list[SourceView]) -> list[SourceView]:
        """Bound model triage while preserving fetched, authoritative and diverse evidence."""
        budget = {"quick": 8, "standard": 18, "deep": 40, "overnight": 80}[spec.mode]
        per_domain = {"quick": 2, "standard": 3, "deep": 5, "overnight": 8}[spec.mode]
        category_bonus = {
            "registry": 35,
            "person-registry": 35,
            "network-registry": 35,
            "academic": 30,
            "archive": 28,
            "news-index": 24,
            "reference": 22,
            "code": 20,
            "public-social": 16,
        }
        needle = f"{spec.topic} {spec.angle}".strip()

        def score(source: SourceView) -> tuple[float, int]:
            text = f"{source.title} {source.snippet} {source.url}"
            value = 45.0 if source.fetched else 0.0
            value += category_bonus.get(source.category, 10)
            value += lexical_overlap(needle, text) * 60
            value += max(0, 12 - min(12, source.rank or 12))
            return value, -source.id

        selected: list[SourceView] = []
        domains: dict[str, int] = {}
        for source in sorted(sources, key=score, reverse=True):
            domain = source.domain or "unknown"
            if domains.get(domain, 0) >= per_domain:
                continue
            selected.append(source)
            domains[domain] = domains.get(domain, 0) + 1
            if len(selected) >= budget:
                break
        return selected

    async def _synthesize(self, run_id: str, spec: ResearchSpec) -> str:
        sources = self.storage.sources_for_run(run_id, limit=100)
        claims = self.storage.claims_for_run(run_id, limit=120)
        assessments = {
            int(item["claim_id"]): item for item in self.storage.claim_assessments_for_run(run_id, limit=200)
        }
        if not sources:
            return "No sources were discovered. Check the search backend and retry."
        if self.provider is None:
            summary = self._fallback_summary(
                sources,
                claims,
                reason="No LLM provider was configured; this is a deterministic evidence brief.",
            )
            return summary + self._local_evidence_appendix(run_id)
        payload = {
            "research": {"topic": spec.topic, "angle": spec.angle, "mode": spec.mode},
            "coverage": self._research_state(run_id),
            "observation_capsules": self._agent_observation_capsules(run_id),
            "grounded_claims": [
                {
                    "claim_id": c["id"],
                    "claim": c["claim_text"],
                    "source_id": c["source_id"],
                    "source_domain": c.get("domain"),
                    "confidence": c["confidence"],
                    "observed_at": c.get("observed_at"),
                    "importance": c.get("importance"),
                    "rarity": c.get("rarity"),
                    "quote": c.get("quote", "")[:500],
                    "verified_span": bool(c.get("verified_span")),
                    "assessment": assessments.get(int(c["id"]), {}),
                }
                for c in claims[:100]
            ],
        }
        from importlib.resources import files

        system = files("traceweave.prompts").joinpath("synthesis.txt").read_text(encoding="utf-8")
        system += "\n\n" + self.skills.for_task("synthesis")
        try:
            organization = await self.provider.json(
                system=system, user=json.dumps(payload, ensure_ascii=False), task="synthesis", run_id=run_id
            )
            summary = self._render_grounded_synthesis(
                run_id,
                spec,
                claims,
                assessments,
                payload["observation_capsules"],
                organization,
            )
            return summary + self._local_evidence_appendix(run_id)
        except (LLMError, ValueError, TypeError) as exc:
            await self._emit(run_id, "synthesis.failed", f"LLM synthesis unavailable: {exc}")
            summary = self._fallback_summary(
                sources,
                claims,
                reason=f"Generative synthesis was unavailable ({exc}); evidence state remains saved.",
            )
            return summary + self._local_evidence_appendix(run_id)

    def _render_grounded_synthesis(
        self,
        run_id: str,
        spec: ResearchSpec,
        claims: list[dict],
        assessments: dict[int, dict],
        observations: list[dict[str, object]],
        organization: dict,
    ) -> str:
        """Render facts from persisted records; the model controls grouping only."""
        by_claim = {int(claim["id"]): claim for claim in claims}
        by_observation = {int(item["id"]): item for item in observations}

        def ids(values: object, allowed: dict[int, object]) -> list[int]:
            if not isinstance(values, list):
                return []
            result: list[int] = []
            for value in values:
                try:
                    item_id = int(value)
                except (TypeError, ValueError):
                    continue
                if item_id in allowed and item_id not in result:
                    result.append(item_id)
            return result

        def heading(value: object, fallback: str) -> str:
            text = " ".join(str(value or "").split())[:90]
            if not text or "http" in text.casefold() or "[s" in text.casefold():
                return fallback
            return text

        verdict_counts = {
            verdict: sum(1 for item in assessments.values() if item.get("verdict") == verdict)
            for verdict in ("corroborated", "single_source", "contested", "insufficient")
        }
        lines = [
            f"# Evidence-grounded report — {spec.topic}",
            "",
            "## Scope and evidence state",
            "",
            f"- Grounded literal-span claims: {len(claims)}",
            f"- Independently corroborated: {verdict_counts['corroborated']}",
            f"- Single-source: {verdict_counts['single_source']}",
            f"- Contested: {verdict_counts['contested']}",
            f"- Insufficient/unassessed: {verdict_counts['insufficient']}",
            "",
            "Only a `corroborated` verdict means independent-domain corroboration. "
            "Official-source claims can still be single-source.",
            "",
            "## Findings organized by the lead agent",
        ]
        used_claims: set[int] = set()
        groups = organization.get("finding_groups", [])
        if not isinstance(groups, list):
            groups = []
        for index, group in enumerate(groups[:16], 1):
            if not isinstance(group, dict):
                continue
            group_ids = ids(group.get("claim_ids"), by_claim)
            if not group_ids:
                continue
            lines.extend(("", f"### {heading(group.get('heading'), f'Finding group {index}')}", ""))
            for claim_id in group_ids:
                used_claims.add(claim_id)
                self._append_grounded_claim(lines, by_claim[claim_id], assessments.get(claim_id, {}))
        remaining = [claim_id for claim_id in by_claim if claim_id not in used_claims]
        if remaining:
            lines.extend(("", "### Remaining grounded claims", ""))
            for claim_id in remaining:
                self._append_grounded_claim(lines, by_claim[claim_id], assessments.get(claim_id, {}))
        if not claims:
            lines.extend(
                ("", "No literal-grounded claim passed extraction; source records remain leads only.")
            )

        used_observations: set[int] = set()
        observation_groups = organization.get("observation_groups", [])
        if not isinstance(observation_groups, list):
            observation_groups = []
        for index, group in enumerate(observation_groups[:12], 1):
            if not isinstance(group, dict):
                continue
            group_ids = ids(group.get("observation_ids"), by_observation)
            if not group_ids:
                continue
            if not used_observations:
                lines.extend(("", "## Public observation leads"))
            lines.extend(("", f"### {heading(group.get('heading'), f'Observation group {index}')}", ""))
            for observation_id in group_ids:
                used_observations.add(observation_id)
                item = by_observation[observation_id]
                source_id = item.get("source_id") or "?"
                locator = json.dumps(item.get("locator") or {}, ensure_ascii=False)
                lines.append(
                    f"- O{observation_id} [S{source_id}] `{item.get('kind')}`: "
                    f"{item.get('text') or ''} (confidence={item.get('confidence')}, locator={locator})"
                )
        if used_observations:
            lines.extend(
                (
                    "",
                    "Observation leads describe visible/OCR/metadata records; they are not identity proof or corroborated facts.",
                )
            )

        lines.extend(("", "## Reviewable identity and media hypotheses", ""))
        hypotheses = self.storage.identity_hypotheses_for_run(run_id, 80)
        matches = self.storage.artifact_matches_for_run(run_id, 80)
        if not hypotheses and not matches:
            lines.append("- No identity or media-match hypothesis was produced.")
        for item in hypotheses:
            evidence = ", ".join(f"C{value}" for value in item["evidence_claim_ids"]) or "none"
            lines.append(
                f"- E{item['left_entity_id']}↔E{item['right_entity_id']}: {item['verdict']} "
                f"(confidence={float(item['confidence']):.2f}; evidence={evidence})."
            )
        for item in matches:
            lines.append(
                f"- {item['left_artifact_id']}↔{item['right_artifact_id']}: {item['verdict']} "
                f"(perceptual distance={float(item['distance']):.0f}); this is not face identification."
            )

        questions = organization.get("unresolved_questions", [])
        coverage_gaps = self._research_state(run_id).get("coverage_gaps", [])
        lines.extend(("", "## Unresolved questions and coverage gaps", ""))
        for gap in coverage_gaps if isinstance(coverage_gaps, list) else []:
            lines.append(f"- Coverage gap: {str(gap)[:300]}")
        if isinstance(questions, list):
            for value in questions[:12]:
                question = " ".join(str(value).split())[:400].rstrip(". ?")
                if question:
                    lines.append(f"- Review question: {question}?")
        if len(lines) and not coverage_gaps and not questions:
            lines.append("- No additional gap was proposed; this does not imply completeness.")
        return "\n".join(lines)

    @staticmethod
    def _append_grounded_claim(lines: list[str], claim: dict, assessment: dict) -> None:
        verdict = str(assessment.get("verdict") or "unassessed")
        confidence = float(assessment.get("confidence") or claim.get("confidence") or 0)
        lines.append(
            f"- **C{claim['id']} — {verdict}** [S{claim['source_id']}] {claim['claim_text']} "
            f"(confidence={confidence:.2f})"
        )
        quote = " ".join(str(claim.get("quote") or "").split())[:700]
        if quote:
            lines.append(f"  - Literal evidence: “{quote}”")
        if claim.get("observed_at"):
            lines.append(f"  - Observed at: {claim['observed_at']}")
        if assessment.get("rationale"):
            lines.append(f"  - Assessment: {str(assessment['rationale'])[:500]}")

    def _local_evidence_appendix(self, run_id: str) -> str:
        observations = self._reportable_observations(run_id, 80)
        edges = self.storage.research_edges_for_run(run_id, 250)
        if not observations and not edges:
            return ""
        lines = ["", "", "## Locally retained evidence"]
        if observations:
            lines.append("### Visual, OCR and metadata observations")
            for observation in observations[:12]:
                source = f"S{observation['source_id']}" if observation.get("source_id") else "S?"
                artifact = str(observation.get("artifact_id") or "no-artifact")
                text = " ".join(str(observation.get("value_text") or "").split())[:240]
                lines.append(f"- [{source}] {observation['kind']} ({artifact}): {text}")
        if edges:
            lines.extend(("", "### Discovery/provenance paths", f"Stored graph edges: {len(edges)}."))
            lines.append("Full observations and paths remain in findings.json and graph exports.")
            for edge in edges[:16]:
                lines.append(
                    f"- {edge['from_type']}:{edge['from_id']} → {edge['relation']} → "
                    f"{edge['to_type']}:{edge['to_id']}"
                )
        return "\n".join(lines)

    @staticmethod
    def _fallback_summary(sources: list[SourceView], claims: list[dict], *, reason: str) -> str:
        lines = [
            "Evidence brief (deterministic fallback)",
            reason,
            "",
            f"Collected {len(sources)} sources and {len(claims)} literal-grounded claims.",
            "",
            "Grounded claims:",
        ]
        if claims:
            for claim in claims[:12]:
                confidence = float(claim.get("confidence") or 0)
                lines.append(f"- [S{claim['source_id']}] {claim['claim_text']} (confidence={confidence:.2f})")
        else:
            lines.append("- No literal-grounded claims passed the extraction gate.")
        lines.extend(("", "Top sources:"))
        for source in sources[:15]:
            score = f"I={source.importance:.0f}" if source.importance is not None else "unscored"
            lines.append(f"- [S{source.id}] {source.title or source.url} ({score}) — {source.url}")
        lines.extend(
            (
                "",
                "Unresolved: interpretive synthesis and contradiction reconciliation were not completed; "
                "review the cited source records before making consequential decisions.",
            )
        )
        return "\n".join(lines)
