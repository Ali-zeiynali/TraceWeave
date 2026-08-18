from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import suppress

from traceweave.config import Settings
from traceweave.fetcher import FetchError, SafeFetcher
from traceweave.models import ProgressEvent, ResearchSpec, SourceView
from traceweave.planner import Planner
from traceweave.providers.base import LLMProvider
from traceweave.search.base import SearchBackend, SearchError
from traceweave.storage import Storage

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
        )
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
        self.storage.update_run(run_id, status="running", last_error=None)
        await self._emit(run_id, "run.started", f"Research started/resumed: {spec.topic}")
        try:
            for round_no in range(int(row["current_round"]) + 1, spec.resolved_rounds() + 1):
                await self._run_round(run_id, spec, round_no)
                self.storage.update_run(run_id, current_round=round_no)
                await self._emit(
                    run_id, "round.completed", f"Completed round {round_no}/{spec.resolved_rounds()}", round=round_no
                )
            summary = await self._synthesize(run_id, spec)
            self.storage.update_run(run_id, status="completed", final_summary=summary)
            await self._emit(run_id, "run.completed", "Research completed", source_count=len(self.storage.sources_for_run(run_id)))
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
                plan = await self.planner.initial(spec)
            else:
                plan = await self.planner.replan(
                    spec,
                    round_no=round_no,
                    completed_queries=self.storage.completed_queries(run_id),
                    sources=self.storage.sources_for_run(run_id, limit=60),
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
        )

        queries = self.storage.pending_queries(run_id, round_no)
        for query in queries:
            await self._emit(run_id, "search.started", f"Searching: {query}", query=query, round=round_no)
            try:
                results = await self.search.search(
                    query,
                    limit=spec.max_results_per_query,
                    language=spec.language,
                )
            except SearchError as exc:
                self.storage.complete_query(run_id, round_no, query, error=str(exc))
                await self._emit(run_id, "search.failed", f"Search failed: {query}: {exc}", query=query)
                continue

            fetch_jobs: list[tuple[int, str]] = []
            for rank, result in enumerate(results, start=1):
                source_id = self.storage.add_search_result(run_id, query, rank, result)
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
                await asyncio.gather(*(self._fetch_source(run_id, sid, url) for sid, url in fetch_jobs))
            self.storage.complete_query(run_id, round_no, query)
            await self._emit(run_id, "search.completed", f"Search completed: {query}", query=query, count=len(results))

    async def _fetch_source(self, run_id: str, source_id: int, url: str) -> None:
        async with self._fetch_sem:
            try:
                result = await self.fetcher.fetch(url)
                self.storage.save_snapshot(
                    source_id=source_id,
                    final_url=result.final_url,
                    status_code=result.status_code,
                    content_type=result.content_type,
                    content_hash=result.content_hash,
                    raw=result.raw,
                    text=result.text,
                    extracted_title=result.title,
                )
                await self._emit(
                    run_id,
                    "source.fetched",
                    f"Fetched source S{source_id}",
                    source_id=source_id,
                    url=result.final_url,
                    bytes=len(result.raw),
                    content_type=result.content_type,
                )
            except FetchError as exc:
                await self._emit(run_id, "source.fetch_failed", f"Could not fetch S{source_id}: {exc}", source_id=source_id, url=url)

    async def _synthesize(self, run_id: str, spec: ResearchSpec) -> str:
        sources = self.storage.sources_for_run(run_id, limit=80)
        if not sources:
            return "No sources were discovered. Check the search backend and retry."
        if self.provider is None:
            lines = [
                "No LLM provider was configured, so TraceWeave completed collection without generative synthesis.",
                "",
                "Top discovered sources:",
            ]
            for source in sources[:20]:
                lines.append(f"- [S{source.id}] {source.title or source.url} — {source.domain}")
            return "\n".join(lines)

        from importlib.resources import files
        system = files("traceweave.prompts").joinpath("synthesis.txt").read_text(encoding="utf-8")
        capsules = []
        char_budget = 48_000
        used = 0
        for source in sources:
            evidence = source.text_excerpt[:2500] if source.fetched else source.snippet[:900]
            capsule = {
                "id": f"S{source.id}",
                "title": source.title,
                "url": source.url,
                "domain": source.domain,
                "published_at": source.published_at,
                "category": source.category,
                "evidence": evidence,
                "fetched": source.fetched,
            }
            encoded = json.dumps(capsule, ensure_ascii=False)
            if used + len(encoded) > char_budget:
                break
            capsules.append(capsule)
            used += len(encoded)
        user = json.dumps(
            {"topic": spec.topic, "angle": spec.angle, "sources": capsules},
            ensure_ascii=False,
            indent=2,
        )
        with suppress(Exception):
            return await self.provider.text(system=system, user=user)
        return "Synthesis failed, but all discovered sources and snapshots remain stored for export/resume."
