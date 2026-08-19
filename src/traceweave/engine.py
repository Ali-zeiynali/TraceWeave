from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from math import ceil

from traceweave.analysis import EvidenceAnalyzer
from traceweave.config import Settings
from traceweave.fetcher import BrowserFetcher, FetchError, FetchResult, SafeFetcher
from traceweave.frontier import FrontierManager
from traceweave.models import ProgressEvent, ResearchSpec, SourceView
from traceweave.planner import Planner
from traceweave.providers.base import LLMError, LLMProvider
from traceweave.search.base import SearchBackend, SearchError
from traceweave.storage import Storage
from traceweave.skills import SkillRegistry

ProgressCallback = Callable[[ProgressEvent], Awaitable[None] | None]


class ResearchEngine:
    def __init__(self, *, settings: Settings, storage: Storage, search: SearchBackend, planner: Planner,
                 provider: LLMProvider | None, callback: ProgressCallback | None = None):
        self.settings = settings
        self.storage = storage
        self.search = search
        self.planner = planner
        self.provider = provider
        self.callback = callback
        self.fetcher = SafeFetcher(
            timeout=settings.fetch_timeout_seconds, max_bytes=settings.fetch_max_bytes, user_agent=settings.user_agent
        )
        self.browser = BrowserFetcher(timeout=settings.fetch_timeout_seconds * 1.5, max_bytes=settings.fetch_max_bytes)
        self.frontier = FrontierManager(
            storage, self.fetcher, user_agent=settings.user_agent, respect_robots=settings.respect_robots
        )
        self.analyzer = EvidenceAnalyzer(storage, provider)
        self.skills = SkillRegistry()
        self._fetch_sem = asyncio.Semaphore(settings.fetch_concurrency)

    async def _emit(self, run_id: str | None, kind: str, message: str, **data) -> None:
        self.storage.event(run_id, kind, message, data)
        if self.callback:
            result = self.callback(ProgressEvent(kind=kind, message=message, data=data))
            if asyncio.iscoroutine(result):
                await result

    async def start(self, spec: ResearchSpec) -> str:
        run_id = self.storage.create_run(spec)
        await self._emit(run_id, "run.created", f"Created research run {run_id}", topic=spec.topic)
        return await self.resume(run_id)

    async def resume(self, run_id: str) -> str:
        row = self.storage.get_run(run_id)
        if not row:
            raise KeyError(f"Unknown run: {run_id}")
        spec = self.storage.run_spec(run_id)
        recovered = self.storage.recover_frontier_leases(run_id)
        if recovered:
            await self._emit(run_id, "frontier.recovered", f"Recovered {recovered} leased frontier tasks")
        self.storage.update_run(run_id, status="running", last_error=None)
        await self._emit(run_id, "run.started", f"Research started/resumed: {spec.topic}")
        try:
            for round_no in range(int(row["current_round"]) + 1, spec.resolved_rounds() + 1):
                await self._run_round(run_id, spec, round_no)
                self.storage.update_run(run_id, current_round=round_no)
                await self._emit(run_id, "round.completed", f"Completed round {round_no}/{spec.resolved_rounds()}", round=round_no)
            summary = await self._synthesize(run_id, spec)
            self.storage.update_run(run_id, status="completed", final_summary=summary)
            await self._emit(
                run_id, "run.completed", "Research completed",
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

    async def _run_round(self, run_id: str, spec: ResearchSpec, round_no: int) -> None:
        plan = self.storage.get_plan(run_id, round_no)
        if plan is None:
            if round_no == 1:
                plan = await self.planner.initial(spec, run_id=run_id)
            else:
                plan = await self.planner.replan(
                    spec, round_no=round_no, completed_queries=self.storage.completed_queries(run_id),
                    sources=self.storage.sources_for_run(run_id, limit=60), claims=self.storage.claims_for_run(run_id, 80),
                    run_id=run_id,
                )
            self.storage.save_plan(run_id, round_no, plan)
        await self._emit(
            run_id, "plan.ready", f"Round {round_no} plan: {plan.objective}", round=round_no,
            objective=plan.objective, focus=plan.focus, queries=plan.queries, gaps=plan.gaps,
            source_classes=plan.source_classes,
        )

        for query in self.storage.pending_queries(run_id, round_no):
            await self._search_query(run_id, spec, round_no, query)

        await self._analyze_new_sources(run_id, spec, round_no)
        if self.settings.frontier_enabled and spec.resolved_frontier_pages() > 0 and spec.resolved_depth() > 0:
            await self._crawl_frontier(run_id, spec, round_no)
            await self._analyze_new_sources(run_id, spec, round_no)

    async def _search_query(self, run_id: str, spec: ResearchSpec, round_no: int, query: str) -> None:
        await self._emit(run_id, "search.started", f"Searching: {query}", query=query, round=round_no)
        try:
            results = await self.search.search(query, limit=spec.max_results_per_query, language=spec.language)
        except SearchError as exc:
            self.storage.complete_query(run_id, round_no, query, error=str(exc))
            await self._emit(run_id, "search.failed", f"Search failed: {query}: {exc}", query=query)
            return
        fetch_jobs: list[tuple[int, str]] = []
        for rank, result in enumerate(results, start=1):
            source_id = self.storage.add_search_result(run_id, query, rank, result)
            await self._emit(
                run_id, "source.discovered", result.title or result.url, source_id=source_id, url=result.url,
                title=result.title, engine=result.engine, category=result.category,
                published_at=result.published_at, query=query, rank=rank,
            )
            if rank <= spec.fetch_top_per_query and self.storage.latest_snapshot(source_id) is None:
                fetch_jobs.append((source_id, result.url))
        if fetch_jobs:
            await asyncio.gather(*(self._fetch_source(run_id, spec, sid, url, depth=0) for sid, url in fetch_jobs))
        self.storage.complete_query(run_id, round_no, query)
        await self._emit(run_id, "search.completed", f"Search completed: {query}", query=query, count=len(results))

    async def _fetch_source(self, run_id: str, spec: ResearchSpec, source_id: int, url: str, *, depth: int) -> FetchResult | None:
        async with self._fetch_sem:
            if self.settings.respect_robots and not await self.frontier.allowed(url):
                await self._emit(run_id, "source.robots_blocked", f"robots.txt disallows S{source_id}", source_id=source_id, url=url)
                return None
            try:
                result = await self.fetcher.fetch(url)
                if (
                    self.settings.browser_fallback and "html" in result.content_type.casefold()
                    and len(result.text) < self.settings.browser_min_text_chars
                ):
                    try:
                        browser_result = await self.browser.fetch(url)
                        if len(browser_result.text) > len(result.text):
                            result = browser_result
                            await self._emit(run_id, "source.browser_fallback", f"Browser fallback improved S{source_id}", source_id=source_id)
                    except FetchError as exc:
                        await self._emit(run_id, "source.browser_failed", f"Browser fallback failed for S{source_id}: {exc}", source_id=source_id)
                self.storage.save_snapshot(
                    source_id=source_id, final_url=result.final_url, status_code=result.status_code,
                    content_type=result.content_type, content_hash=result.content_hash, raw=result.raw,
                    text=result.text, extracted_title=result.title, simhash=result.simhash,
                )
                added = 0
                if depth < spec.resolved_depth():
                    added = self.frontier.add_page_links(
                        run_id, spec, source_id=source_id, parent_url=result.final_url,
                        links=result.links, depth=depth + 1,
                    )
                    for feed in result.feeds:
                        self.storage.add_frontier(
                            run_id, feed, parent_source_id=source_id, anchor="feed", relation="feed",
                            depth=min(depth + 1, spec.resolved_depth()), score=0.45,
                        )
                    if self.settings.sitemap_enabled:
                        sitemap_added = await self.frontier.discover_domain(run_id, spec, source_id, result.final_url)
                        added += sitemap_added
                await self._emit(
                    run_id, "source.fetched", f"Fetched source S{source_id}", source_id=source_id,
                    url=result.final_url, bytes=len(result.raw), content_type=result.content_type,
                    links_added=added, depth=depth,
                )
                return result
            except FetchError as exc:
                await self._emit(run_id, "source.fetch_failed", f"Could not fetch S{source_id}: {exc}", source_id=source_id, url=url)
                return None

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
        await self._emit(run_id, "frontier.started", f"Best-first frontier crawl budget: {round_budget}", round=round_no)
        while processed < round_budget:
            items = self.storage.lease_frontier(
                run_id, max_depth=spec.resolved_depth(), min_score=self.settings.frontier_min_score,
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
                    run_id, url, int(item["parent_source_id"]) if item["parent_source_id"] is not None else None,
                    relation=str(item["relation"]),
                )
                await self._emit(
                    run_id, "frontier.visit", f"Crawling S{source_id} score={float(item['score']):.2f}",
                    source_id=source_id, url=url, depth=item["depth"], score=item["score"], relation=item["relation"],
                )
                if self.storage.latest_snapshot(source_id) is None:
                    result = await self._fetch_source(run_id, spec, source_id, url, depth=int(item["depth"]))
                    self.storage.complete_frontier(int(item["id"]), error=None if result else "fetch failed")
                else:
                    self.storage.complete_frontier(int(item["id"]))
        await self._emit(run_id, "frontier.completed", f"Frontier processed {processed} pages", processed=processed,
                         stats=self.storage.frontier_stats(run_id))

    async def _analyze_new_sources(self, run_id: str, spec: ResearchSpec, round_no: int) -> None:
        if not self.settings.triage_enabled:
            return
        analyzed = self.storage.analyzed_source_ids(run_id)
        sources = self.storage.sources_for_run(run_id, limit=500)
        pending = [s for s in sources if s.id not in analyzed]
        if not pending:
            return
        claims_budget = self.settings.claims_max_sources_per_round
        claims_used = 0
        for source in pending:
            full_text = self.storage.snapshot_text(source.id)
            source_for_model = source.model_copy(update={"text_excerpt": full_text[:16000] if full_text else source.text_excerpt})
            snapshot = self.storage.latest_snapshot(source.id)
            duplicate_of = None
            family_key = f"domain:{source.domain}"
            if snapshot and snapshot.get("simhash"):
                duplicate_of = self.storage.find_near_duplicate(run_id, source.id, str(snapshot["simhash"]), max_distance=3)
                family_key = f"source:{duplicate_of}" if duplicate_of else f"sim:{str(snapshot['simhash'])[:12]}"
            result = await self.analyzer.triage(run_id, spec, source_for_model, sources)
            if duplicate_of:
                result = result.model_copy(update={"novelty": min(result.novelty, 12.0)})
            self.storage.save_analysis(run_id, source.id, result, family_key=family_key, duplicate_of=duplicate_of)
            await self._emit(
                run_id, "source.triaged", f"S{source.id} R{result.relevance:.0f} I{result.importance:.0f} N{result.novelty:.0f}",
                source_id=source.id, relevance=result.relevance, importance=result.importance,
                novelty=result.novelty, authority=result.authority, duplicate_of=duplicate_of,
                leads=result.leads, round=round_no,
            )
            if (
                self.settings.claims_enabled and self.provider is not None and full_text and not duplicate_of
                and result.relevance >= self.settings.claim_min_relevance and claims_used < claims_budget
            ):
                claims_used += 1
                claims = await self.analyzer.extract_claims(run_id, spec, source_for_model)
                for claim in claims:
                    start = full_text.find(claim.evidence_quote)
                    if start < 0:
                        continue
                    claim_id = self.storage.add_claim(
                        run_id, source.id, claim_text=claim.claim, subject=claim.subject, predicate=claim.predicate,
                        object_text=claim.object, observed_at=claim.observed_at, confidence=claim.confidence,
                        quote=claim.evidence_quote, char_start=start, char_end=start + len(claim.evidence_quote), verified_span=True,
                    )
                    await self._emit(run_id, "claim.extracted", f"C{claim_id} from S{source.id}: {claim.claim[:120]}",
                                     claim_id=claim_id, source_id=source.id)

    async def _synthesize(self, run_id: str, spec: ResearchSpec) -> str:
        sources = self.storage.sources_for_run(run_id, limit=100)
        claims = self.storage.claims_for_run(run_id, limit=120)
        if not sources:
            return "No sources were discovered. Check the search backend and retry."
        if self.provider is None:
            lines = [
                "No LLM provider was configured, so TraceWeave completed collection/triage without generative synthesis.", "",
                f"Collected {len(sources)} sources and {len(claims)} grounded claims.", "",
                "Top sources:",
            ]
            for source in sources[:25]:
                score = f"I={source.importance:.0f}" if source.importance is not None else "unscored"
                lines.append(f"- [S{source.id}] {source.title or source.url} ({score}) — {source.url}")
            return "\n".join(lines)
        payload = {
            "research": {"topic": spec.topic, "angle": spec.angle, "mode": spec.mode},
            "sources": [
                {"id": s.id, "title": s.title, "url": s.url, "domain": s.domain, "published_at": s.published_at,
                 "relevance": s.relevance, "importance": s.importance, "novelty": s.novelty,
                 "authority": s.authority, "duplicate_of": s.duplicate_of,
                 "snippet": s.snippet[:500], "excerpt": s.text_excerpt[:700]}
                for s in sources[:70]
            ],
            "grounded_claims": [
                {"claim": c["claim_text"], "source_id": c["source_id"], "confidence": c["confidence"],
                 "quote": c.get("quote", "")[:500], "verified_span": bool(c.get("verified_span"))}
                for c in claims[:100]
            ],
        }
        from importlib.resources import files
        system = files("traceweave.prompts").joinpath("synthesis.txt").read_text(encoding="utf-8")
        system += "\n\n" + self.skills.for_task("synthesis")
        try:
            return await self.provider.text(
                system=system, user=json.dumps(payload, ensure_ascii=False), task="synthesis", run_id=run_id
            )
        except LLMError as exc:
            await self._emit(run_id, "synthesis.failed", f"LLM synthesis unavailable: {exc}")
            return f"Synthesis provider failed, but collection/evidence state is saved. Export the run for sources and claims. Error: {exc}"
