from __future__ import annotations

import hashlib
from dataclasses import dataclass

from traceweave.config import Settings
from traceweave.fetcher import SafeFetcher, extract_payload
from traceweave.models import Plan, ResearchSpec, SearchResult
from traceweave.sources.academic import AcademicSources
from traceweave.sources.archives import CommonCrawlSource, WaybackSource
from traceweave.sources.citations import extract_citation_leads
from traceweave.sources.github import GitHubSource
from traceweave.sources.open_web import OpenWebSources
from traceweave.sources.registries import RegistrySources
from traceweave.sources.social import PublicSocialSources
from traceweave.storage import Storage


@dataclass(slots=True)
class SpecialistStats:
    academic: int = 0
    code: int = 0
    citations: int = 0
    archives: int = 0
    registries: int = 0
    social: int = 0
    open_web: int = 0
    errors: list[str] | None = None

    def add_error(self, value: str) -> None:
        if self.errors is None:
            self.errors = []
        self.errors.append(value[:500])


class SpecialistManager:
    """Stage 4 passive specialist-source orchestration.

    It only talks to public APIs / public web archives. It never performs active network probing.
    """

    def __init__(self, settings: Settings, storage: Storage, fetcher: SafeFetcher):
        self.settings = settings
        self.storage = storage
        self.fetcher = fetcher
        self.academic = AcademicSources(
            timeout=settings.search_timeout_seconds, mailto=settings.openalex_mailto
        )
        self.github = GitHubSource(token=settings.github_token, timeout=settings.search_timeout_seconds)
        self.wayback = WaybackSource(timeout=settings.search_timeout_seconds)
        self.commoncrawl = CommonCrawlSource(timeout=settings.search_timeout_seconds)
        self.registries = RegistrySources(
            timeout=settings.search_timeout_seconds, user_agent=settings.user_agent
        )
        self.social = PublicSocialSources(
            timeout=settings.search_timeout_seconds,
            bluesky_enabled=settings.bluesky_enabled,
            telegram_enabled=settings.telegram_public_enabled,
            instagram_enabled=settings.instagram_official_enabled,
        )
        self.open_web = OpenWebSources(
            timeout=settings.search_timeout_seconds, user_agent=settings.user_agent
        )

    async def discover(self, run_id: str, spec: ResearchSpec, plan: Plan, round_no: int) -> SpecialistStats:
        stats = SpecialistStats()
        if spec.mode == "quick":
            return stats
        queries = plan.queries[: self.settings.specialist_queries_per_round]
        if not queries:
            queries = [f"{spec.topic} {spec.angle}".strip()]
        academic_signal = f"{spec.topic} {spec.angle}".casefold()
        academic_relevant = spec.mode in {"deep", "overnight"} or any(
            word in academic_signal
            for word in (
                "academic",
                "paper",
                "study",
                "research literature",
                "science",
                "scientific",
                "medicine",
                "clinical",
                "دانشگاهی",
                "مقاله",
                "پژوهش علمی",
                "مطالعه",
                "علمی",
            )
        )
        if self.settings.academic_enabled and academic_relevant:
            for query in queries[: 2 if spec.mode == "standard" else len(queries)]:
                try:
                    rows = await self.academic.search(query, self.settings.specialist_results_per_query)
                except Exception as exc:
                    stats.add_error(f"academic:{type(exc).__name__}:{exc}")
                    rows = []
                for rank, row in enumerate(rows, 1):
                    sid = self.storage.add_search_result(
                        run_id,
                        f"[academic:r{round_no}] {query}",
                        rank,
                        SearchResult(
                            url=row.url,
                            title=row.title,
                            snippet=row.snippet,
                            engine=row.engine,
                            category=row.category,
                            published_at=row.published_at,
                            raw=row.raw,
                        ),
                    )
                    self.storage.add_research_edge(
                        run_id,
                        from_type="round",
                        from_id=round_no,
                        relation="academic_discovery",
                        to_type="source",
                        to_id=sid,
                        metadata={"query": query, "engine": row.engine},
                    )
                    stats.academic += 1
        if spec.mode in {"deep", "overnight"}:
            for query in queries[:2]:
                rows, errors = await self.open_web.search(query, self.settings.specialist_results_per_query)
                for error in errors:
                    stats.add_error(error)
                for rank, row in enumerate(rows, 1):
                    sid = self.storage.add_search_result(run_id, f"[open-web:r{round_no}] {query}", rank, row)
                    self.storage.add_research_edge(
                        run_id,
                        from_type="round",
                        from_id=round_no,
                        relation="open_web_discovery",
                        to_type="source",
                        to_id=sid,
                        metadata={"query": query, "engine": row.engine},
                    )
                    stats.open_web += 1
        if self.settings.github_enabled and (
            spec.mode in {"deep", "overnight"}
            or any(
                x in f"{spec.topic} {spec.angle}".casefold()
                for x in ("software", "code", "github", "technical", "technology", "api")
            )
        ):
            for query in queries[:2]:
                try:
                    rows = await self.github.search(query, self.settings.specialist_results_per_query)
                except Exception as exc:
                    stats.add_error(f"github:{type(exc).__name__}:{exc}")
                    rows = []
                for rank, row in enumerate(rows, 1):
                    sid = self.storage.add_search_result(
                        run_id,
                        f"[github:r{round_no}] {query}",
                        rank,
                        SearchResult(
                            url=row.url,
                            title=row.title,
                            snippet=row.snippet,
                            engine=row.engine,
                            category=row.category,
                            published_at=row.published_at,
                            raw=row.raw,
                        ),
                    )
                    self.storage.add_research_edge(
                        run_id,
                        from_type="round",
                        from_id=round_no,
                        relation="code_discovery",
                        to_type="source",
                        to_id=sid,
                        metadata={"query": query, "engine": row.engine},
                    )
                    stats.code += 1
        if self.settings.registry_sources_enabled and spec.mode in {"deep", "overnight"}:
            for query in queries[: self.settings.registry_queries_per_round]:
                try:
                    rows = await self.registries.search(query, self.settings.specialist_results_per_query)
                except Exception as exc:
                    stats.add_error(f"registries:{type(exc).__name__}:{exc}")
                    rows = []
                for rank, row in enumerate(rows, 1):
                    sid = self.storage.add_search_result(run_id, f"[registry:r{round_no}] {query}", rank, row)
                    self.storage.add_research_edge(
                        run_id,
                        from_type="round",
                        from_id=round_no,
                        relation="registry_discovery",
                        to_type="source",
                        to_id=sid,
                        metadata={"query": query, "engine": row.engine},
                    )
                    stats.registries += 1
        if self.settings.public_social_enabled and spec.mode in {"deep", "overnight"}:
            for query in queries[: self.settings.social_queries_per_round]:
                rows, errors = await self.social.search(query, self.settings.specialist_results_per_query)
                for error in errors:
                    stats.add_error(error)
                for rank, row in enumerate(rows, 1):
                    sid = self.storage.add_search_result(run_id, f"[social:r{round_no}] {query}", rank, row)
                    self.storage.add_research_edge(
                        run_id,
                        from_type="round",
                        from_id=round_no,
                        relation="public_social_discovery",
                        to_type="source",
                        to_id=sid,
                        metadata={"query": query, "engine": row.engine},
                    )
                    stats.social += 1
        return stats

    def snowball_citations(
        self, run_id: str, spec: ResearchSpec, source_id: int, text: str, *, depth: int = 1
    ) -> int:
        count = 0
        for lead in extract_citation_leads(text, limit=60):
            cid = self.storage.add_citation(
                run_id, source_id, target_url=lead.url, kind=lead.kind, label=lead.label
            )
            self.storage.add_frontier(
                run_id,
                lead.url,
                parent_source_id=source_id,
                anchor=lead.label,
                relation="citation",
                depth=min(depth, spec.resolved_depth()),
                score=0.86 if lead.kind in {"doi", "arxiv"} else 0.72,
            )
            self.storage.add_research_edge(
                run_id,
                from_type="source",
                from_id=source_id,
                relation="cites",
                to_type="citation",
                to_id=cid,
                metadata={"kind": lead.kind, "url": lead.url},
            )
            count += 1
        return count

    async def archive_top_sources(self, run_id: str, spec: ResearchSpec) -> int:
        if not self.settings.archives_enabled or spec.mode == "quick":
            return 0
        rows = self.storage.sources_for_run(run_id, 100)
        # Prefer high-value, fetched, non-archive HTTP sources and keep the budget intentionally small.
        selected = [s for s in rows if s.url.startswith(("http://", "https://")) and s.category != "archive"]
        selected.sort(key=lambda s: (s.importance or s.relevance or 0, 1 if s.fetched else 0), reverse=True)
        selected = selected[: self.settings.archive_sources_per_round]
        added = 0
        for source in selected:
            if (
                self.settings.wayback_enabled
                and (self.storage.source_stage_state(run_id, source.id, "archive:wayback") or {}).get(
                    "status"
                )
                != "done"
            ):
                try:
                    captures = await self.wayback.captures(
                        source.url, self.settings.archive_captures_per_source
                    )
                    self.storage.mark_source_stage(
                        run_id, source.id, "archive:wayback", result_count=len(captures)
                    )
                except Exception as exc:
                    captures = []
                    self.storage.mark_source_stage(
                        run_id, source.id, "archive:wayback", status="error", error=str(exc)
                    )
                for capture in captures:
                    cap_id = self.storage.add_archive_capture(
                        run_id,
                        source.id,
                        engine=capture.engine,
                        captured_at=capture.captured_at,
                        capture_url=capture.capture_url,
                        mime=capture.mime,
                        status_code=capture.status,
                        digest=capture.digest,
                        raw=capture.raw,
                    )
                    self.storage.add_research_edge(
                        run_id,
                        from_type="source",
                        from_id=source.id,
                        relation="archive_capture",
                        to_type="archive",
                        to_id=cap_id,
                        metadata={"engine": "wayback", "captured_at": capture.captured_at},
                    )
                    # Add the Wayback URL as a normal source as well so it can go through triage/claims.
                    sid = self.storage.add_search_result(
                        run_id,
                        f"[archive] {source.url}",
                        added + 1,
                        SearchResult(
                            url=capture.capture_url,
                            title=f"Archived: {source.title or source.url}",
                            snippet=f"Wayback capture {capture.captured_at}",
                            engine="wayback",
                            category="archive",
                            published_at=capture.captured_at,
                            raw=capture.raw or {},
                        ),
                    )
                    self.storage.add_research_edge(
                        run_id,
                        from_type="archive",
                        from_id=cap_id,
                        relation="materialized_as",
                        to_type="source",
                        to_id=sid,
                    )
                    added += 1
            if (
                self.settings.commoncrawl_enabled
                and spec.mode in {"deep", "overnight"}
                and (self.storage.source_stage_state(run_id, source.id, "archive:commoncrawl") or {}).get(
                    "status"
                )
                != "done"
            ):
                try:
                    captures = await self.commoncrawl.captures(
                        source.url, min(2, self.settings.archive_captures_per_source)
                    )
                    self.storage.mark_source_stage(
                        run_id, source.id, "archive:commoncrawl", result_count=len(captures)
                    )
                except Exception as exc:
                    captures = []
                    self.storage.mark_source_stage(
                        run_id, source.id, "archive:commoncrawl", status="error", error=str(exc)
                    )
                for capture in captures:
                    cap_id = self.storage.add_archive_capture(
                        run_id,
                        source.id,
                        engine=capture.engine,
                        captured_at=capture.captured_at,
                        capture_url=capture.capture_url,
                        mime=capture.mime,
                        status_code=capture.status,
                        digest=capture.digest,
                        raw=capture.raw,
                    )
                    self.storage.add_research_edge(
                        run_id,
                        from_type="source",
                        from_id=source.id,
                        relation="archive_capture",
                        to_type="archive",
                        to_id=cap_id,
                        metadata={"engine": "commoncrawl", "captured_at": capture.captured_at},
                    )
                    try:
                        raw, ctype = await self.commoncrawl.fetch_capture(
                            capture, max_bytes=self.settings.pdf_max_bytes
                        )
                        text, _title, _links, _feeds = extract_payload(raw, ctype or capture.mime, source.url)
                        digest = hashlib.sha256(raw).hexdigest()
                        self.storage.save_archive_content(cap_id, raw=raw, text=text, content_hash=digest)
                    except Exception:
                        pass
                    added += 1
        return added
