from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from traceweave.models import Plan, ResearchSpec, SearchResult, SourceView, TriageResult, utc_now
from traceweave.utils import canonicalize_url, lexical_overlap, metadata_published_at, words

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    angle TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL,
    language TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    current_round INTEGER NOT NULL DEFAULT 0,
    max_rounds INTEGER NOT NULL,
    max_results_per_query INTEGER NOT NULL,
    fetch_top_per_query INTEGER NOT NULL,
    max_depth INTEGER NOT NULL DEFAULT 0,
    max_frontier_pages INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    final_summary TEXT
);

CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    round_no INTEGER NOT NULL,
    objective TEXT NOT NULL,
    focus_json TEXT NOT NULL,
    queries_json TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    gaps_json TEXT NOT NULL DEFAULT '[]',
    source_classes_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    UNIQUE(run_id, round_no)
);

CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    round_no INTEGER NOT NULL,
    query TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    error TEXT,
    UNIQUE(run_id, round_no, query)
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_url TEXT NOT NULL UNIQUE,
    url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT '',
    first_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_sources (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    search_query TEXT NOT NULL,
    rank INTEGER NOT NULL DEFAULT 0,
    snippet TEXT NOT NULL DEFAULT '',
    engine TEXT NOT NULL DEFAULT 'unknown',
    category TEXT NOT NULL DEFAULT 'web',
    published_at TEXT,
    raw_json TEXT NOT NULL DEFAULT '{}',
    discovered_at TEXT NOT NULL,
    PRIMARY KEY(run_id, source_id, search_query, engine, category)
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    fetched_at TEXT NOT NULL,
    final_url TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    content_type TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL,
    raw_path TEXT,
    text_path TEXT,
    extracted_title TEXT NOT NULL DEFAULT '',
    simhash TEXT NOT NULL DEFAULT '',
    UNIQUE(source_id, content_hash)
);

CREATE TABLE IF NOT EXISTS source_analysis (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    relevance REAL NOT NULL DEFAULT 0,
    importance REAL NOT NULL DEFAULT 0,
    novelty REAL NOT NULL DEFAULT 0,
    authority REAL NOT NULL DEFAULT 0,
    rationale TEXT NOT NULL DEFAULT '',
    topics_json TEXT NOT NULL DEFAULT '[]',
    leads_json TEXT NOT NULL DEFAULT '[]',
    family_key TEXT NOT NULL DEFAULT '',
    duplicate_of INTEGER REFERENCES sources(id),
    analyzed_at TEXT NOT NULL,
    PRIMARY KEY(run_id, source_id)
);

CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    claim_text TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    predicate TEXT NOT NULL DEFAULT '',
    object_text TEXT NOT NULL DEFAULT '',
    observed_at TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'extracted',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id INTEGER NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    quote TEXT NOT NULL,
    char_start INTEGER,
    char_end INTEGER,
    verified_span INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claim_assessments (
    claim_id INTEGER PRIMARY KEY REFERENCES claims(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    verdict TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    supporting_claim_ids_json TEXT NOT NULL DEFAULT '[]',
    conflicting_claim_ids_json TEXT NOT NULL DEFAULT '[]',
    rationale TEXT NOT NULL DEFAULT '',
    assessed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS frontier (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    canonical_url TEXT NOT NULL,
    url TEXT NOT NULL,
    parent_source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    anchor TEXT NOT NULL DEFAULT '',
    relation TEXT NOT NULL DEFAULT 'link',
    depth INTEGER NOT NULL DEFAULT 1,
    score REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    domain TEXT NOT NULL DEFAULT '',
    discovered_at TEXT NOT NULL,
    leased_at TEXT,
    completed_at TEXT,
    error TEXT,
    UNIQUE(run_id, canonical_url)
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    active_run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
    angle TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'standard',
    language TEXT NOT NULL DEFAULT 'all',
    shell_enabled INTEGER NOT NULL DEFAULT 0,
    onboarding_complete INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS router_credentials (
    credential_key TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    credential_id TEXT NOT NULL,
    successes INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    cooldown_until REAL NOT NULL DEFAULT 0,
    last_status INTEGER,
    last_error TEXT,
    latency_ema REAL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS router_deployments (
    deployment_key TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    credential_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    successes INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    cooldown_until REAL NOT NULL DEFAULT 0,
    latency_ema REAL,
    last_error TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS router_task_health (
    deployment_key TEXT NOT NULL,
    task TEXT NOT NULL,
    successes INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    cooldown_until REAL NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(deployment_key, task)
);

CREATE TABLE IF NOT EXISTS router_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    task TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    credential_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    deployment_key TEXT NOT NULL,
    ok INTEGER NOT NULL,
    failure_kind TEXT,
    status_code INTEGER,
    latency_seconds REAL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    response_id TEXT NOT NULL DEFAULT '',
    message TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS domain_state (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    domain TEXT NOT NULL,
    sitemap_checked INTEGER NOT NULL DEFAULT 0,
    robots_checked INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(run_id, domain)
);


CREATE TABLE IF NOT EXISTS archive_captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    engine TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    capture_url TEXT NOT NULL,
    mime TEXT NOT NULL DEFAULT '',
    status_code INTEGER,
    digest TEXT NOT NULL DEFAULT '',
    raw_json TEXT NOT NULL DEFAULT '{}',
    raw_path TEXT,
    text_path TEXT,
    content_hash TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(run_id, source_id, engine, captured_at, capture_url)
);

CREATE TABLE IF NOT EXISTS source_stage_state (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'done',
    result_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    checked_at TEXT NOT NULL,
    PRIMARY KEY(run_id, source_id, stage)
);

CREATE TABLE IF NOT EXISTS citations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    target_url TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'url',
    label TEXT NOT NULL DEFAULT '',
    target_source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, source_id, target_url)
);

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    canonical_name TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'unknown',
    description TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(run_id, canonical_name, entity_type)
);

CREATE TABLE IF NOT EXISTS entity_aliases (
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(entity_id, alias)
);

CREATE TABLE IF NOT EXISTS identity_hypotheses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    left_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    right_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    verdict TEXT NOT NULL DEFAULT 'uncertain',
    confidence REAL NOT NULL DEFAULT 0.5,
    evidence_claim_ids_json TEXT NOT NULL DEFAULT '[]',
    rationale TEXT NOT NULL DEFAULT '',
    assessed_at TEXT NOT NULL,
    UNIQUE(run_id, left_entity_id, right_entity_id),
    CHECK(left_entity_id < right_entity_id)
);

CREATE TABLE IF NOT EXISTS relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    predicate TEXT NOT NULL,
    target_entity_id INTEGER REFERENCES entities(id) ON DELETE CASCADE,
    target_text TEXT NOT NULL DEFAULT '',
    claim_id INTEGER REFERENCES claims(id) ON DELETE SET NULL,
    source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, source_entity_id, predicate, target_entity_id, target_text, claim_id)
);

CREATE TABLE IF NOT EXISTS timeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    event_time TEXT NOT NULL,
    label TEXT NOT NULL,
    entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL,
    claim_id INTEGER REFERENCES claims(id) ON DELETE SET NULL,
    source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, event_time, label, claim_id)
);

CREATE TABLE IF NOT EXISTS research_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    from_type TEXT NOT NULL,
    from_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    to_type TEXT NOT NULL,
    to_id TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(run_id, from_type, from_id, relation, to_type, to_id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT REFERENCES runs(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_tasks (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 100,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    available_at TEXT NOT NULL,
    lease_owner TEXT,
    lease_expires_at TEXT,
    result_json TEXT,
    last_error TEXT,
    dedupe_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(run_id, dedupe_key)
);

CREATE TABLE IF NOT EXISTS research_task_dependencies (
    task_id TEXT NOT NULL REFERENCES research_tasks(id) ON DELETE CASCADE,
    depends_on_task_id TEXT NOT NULL REFERENCES research_tasks(id) ON DELETE CASCADE,
    PRIMARY KEY(task_id, depends_on_task_id),
    CHECK(task_id <> depends_on_task_id)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    snapshot_id INTEGER REFERENCES snapshots(id) ON DELETE SET NULL,
    sha256 TEXT NOT NULL,
    media_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    path TEXT NOT NULL,
    sensitivity TEXT NOT NULL DEFAULT 'public',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(run_id, sha256, media_type)
);

CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    snapshot_id INTEGER REFERENCES snapshots(id) ON DELETE SET NULL,
    artifact_id TEXT REFERENCES artifacts(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    value_text TEXT NOT NULL,
    locator_json TEXT NOT NULL DEFAULT '{}',
    confidence REAL NOT NULL DEFAULT 0.5,
    importance REAL NOT NULL DEFAULT 0,
    rarity REAL NOT NULL DEFAULT 0,
    sensitivity TEXT NOT NULL DEFAULT 'public',
    status TEXT NOT NULL DEFAULT 'observed',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifact_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    left_artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    right_artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    algorithm TEXT NOT NULL,
    distance REAL NOT NULL,
    verdict TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, left_artifact_id, right_artifact_id, algorithm),
    CHECK(left_artifact_id < right_artifact_id)
);

CREATE TABLE IF NOT EXISTS media_leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'image',
    alt_text TEXT NOT NULL DEFAULT '',
    width INTEGER,
    height INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    artifact_id TEXT REFERENCES artifacts(id) ON DELETE SET NULL,
    last_error TEXT,
    discovered_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(run_id, source_id, canonical_url)
);

CREATE INDEX IF NOT EXISTS idx_queries_run_round ON queries(run_id, round_no, status);
CREATE INDEX IF NOT EXISTS idx_run_sources_run ON run_sources(run_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_source ON snapshots(source_id, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_analysis_run ON source_analysis(run_id, relevance DESC);
CREATE INDEX IF NOT EXISTS idx_claims_run ON claims(run_id, source_id);
CREATE INDEX IF NOT EXISTS idx_claim_assessments_run ON claim_assessments(run_id, verdict);
CREATE INDEX IF NOT EXISTS idx_frontier_run ON frontier(run_id, status, score DESC);
CREATE INDEX IF NOT EXISTS idx_archive_run ON archive_captures(run_id, source_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_citations_run ON citations(run_id, source_id);
CREATE INDEX IF NOT EXISTS idx_source_stage_run ON source_stage_state(run_id, source_id, stage);
CREATE INDEX IF NOT EXISTS idx_entities_run ON entities(run_id, entity_type, canonical_name);
CREATE INDEX IF NOT EXISTS idx_identity_run ON identity_hypotheses(run_id, verdict);
CREATE INDEX IF NOT EXISTS idx_relationships_run ON relationships(run_id, source_entity_id);
CREATE INDEX IF NOT EXISTS idx_timeline_run ON timeline_events(run_id, event_time);
CREATE INDEX IF NOT EXISTS idx_research_edges_run ON research_edges(run_id, from_type, to_type);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, id);
CREATE INDEX IF NOT EXISTS idx_router_attempts_time ON router_attempts(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_lease ON research_tasks(run_id, state, available_at, priority);
CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id, source_id);
CREATE INDEX IF NOT EXISTS idx_observations_run ON observations(run_id, importance DESC, rarity DESC);
CREATE INDEX IF NOT EXISTS idx_artifact_matches_run ON artifact_matches(run_id, verdict, distance);
CREATE INDEX IF NOT EXISTS idx_media_leads_run ON media_leads(run_id, status, source_id);
"""


class Storage:
    def __init__(self, db_path: Path, data_dir: Path):
        self.db_path = Path(db_path)
        self.data_dir = Path(data_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "sources").mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            # In-place migration from v0.1 databases.
            self._ensure_column(conn, "runs", "max_depth", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "runs", "max_frontier_pages", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "plans", "gaps_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "plans", "source_classes_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "snapshots", "simhash", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "runs", "deadline_minutes", "INTEGER NOT NULL DEFAULT 45")
            self._ensure_column(conn, "runs", "max_model_calls", "INTEGER NOT NULL DEFAULT 80")
            self._ensure_column(conn, "runs", "max_vision_calls", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "runs", "allow_remote_vision", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "runs", "retention", "TEXT NOT NULL DEFAULT 'manual'")
            self._ensure_column(conn, "runs", "deadline_at", "TEXT")
            self._ensure_column(
                conn, "claims", "snapshot_id", "INTEGER REFERENCES snapshots(id) ON DELETE SET NULL"
            )
            self._ensure_column(conn, "claims", "importance", "REAL NOT NULL DEFAULT 0")
            self._ensure_column(conn, "claims", "rarity", "REAL NOT NULL DEFAULT 0")
            self._ensure_column(conn, "claims", "sensitivity", "TEXT NOT NULL DEFAULT 'public'")
            self._ensure_column(
                conn, "evidence", "snapshot_id", "INTEGER REFERENCES snapshots(id) ON DELETE SET NULL"
            )
            self._ensure_column(conn, "router_attempts", "prompt_tokens", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "router_attempts", "completion_tokens", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "router_attempts", "total_tokens", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "router_attempts", "response_id", "TEXT NOT NULL DEFAULT ''")
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version,name,applied_at) VALUES (?,?,?)",
                (2, "durable-tasks-artifacts-and-budgets", utc_now()),
            )

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    # ---------- runs / plans / queries ----------
    def create_run(self, spec: ResearchSpec) -> str:
        run_id = uuid.uuid4().hex[:12]
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO runs
                   (id, topic, angle, mode, language, status, created_at, updated_at,
                    current_round, max_rounds, max_results_per_query, fetch_top_per_query,
                    max_depth, max_frontier_pages, deadline_minutes, max_model_calls,
                    max_vision_calls, allow_remote_vision, retention, deadline_at)
                   VALUES (?, ?, ?, ?, ?, 'created', ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    spec.topic,
                    spec.angle,
                    spec.mode,
                    spec.language,
                    now,
                    now,
                    spec.resolved_rounds(),
                    spec.max_results_per_query,
                    spec.fetch_top_per_query,
                    spec.resolved_depth(),
                    spec.resolved_frontier_pages(),
                    spec.resolved_deadline_minutes(),
                    spec.resolved_model_calls(),
                    spec.max_vision_calls,
                    int(spec.allow_remote_vision),
                    spec.retention,
                    (datetime.now(UTC) + timedelta(minutes=spec.resolved_deadline_minutes())).isoformat(),
                ),
            )
        return run_id

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def latest_run(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def run_spec(self, run_id: str) -> ResearchSpec:
        row = self.get_run(run_id)
        if not row:
            raise KeyError(f"Unknown run: {run_id}")
        return ResearchSpec(
            topic=row["topic"],
            angle=row["angle"],
            mode=row["mode"],
            language=row["language"],
            max_rounds=row["max_rounds"],
            max_results_per_query=row["max_results_per_query"],
            fetch_top_per_query=row["fetch_top_per_query"],
            max_depth=row.get("max_depth", 0),
            max_frontier_pages=row.get("max_frontier_pages", 0),
            deadline_minutes=row.get("deadline_minutes"),
            max_model_calls=row.get("max_model_calls"),
            max_vision_calls=row.get("max_vision_calls", 0),
            allow_remote_vision=bool(row.get("allow_remote_vision", 0)),
            retention=row.get("retention", "manual"),
        )

    def update_run(self, run_id: str, **fields: Any) -> None:
        allowed = {"status", "current_round", "last_error", "final_summary"}
        pairs = [(k, v) for k, v in fields.items() if k in allowed]
        if not pairs:
            return
        pairs.append(("updated_at", utc_now()))
        with self.connect() as conn:
            conn.execute(
                "UPDATE runs SET " + ", ".join(f"{k}=?" for k, _ in pairs) + " WHERE id=?",
                [v for _, v in pairs] + [run_id],
            )

    def save_plan(self, run_id: str, round_no: int, plan: Plan) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO plans(run_id, round_no, objective, focus_json, queries_json, rationale,
                                      gaps_json, source_classes_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id, round_no) DO UPDATE SET
                     objective=excluded.objective, focus_json=excluded.focus_json,
                     queries_json=excluded.queries_json, rationale=excluded.rationale,
                     gaps_json=excluded.gaps_json, source_classes_json=excluded.source_classes_json""",
                (
                    run_id,
                    round_no,
                    plan.objective,
                    json.dumps(plan.focus, ensure_ascii=False),
                    json.dumps(plan.queries, ensure_ascii=False),
                    plan.rationale,
                    json.dumps(plan.gaps, ensure_ascii=False),
                    json.dumps(plan.source_classes, ensure_ascii=False),
                    utc_now(),
                ),
            )
            for query in plan.queries:
                conn.execute(
                    "INSERT OR IGNORE INTO queries(run_id, round_no, query, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
                    (run_id, round_no, query, utc_now()),
                )

    def get_plan(self, run_id: str, round_no: int) -> Plan | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM plans WHERE run_id=? AND round_no=?", (run_id, round_no)
            ).fetchone()
        if not row:
            return None
        return Plan(
            objective=row["objective"],
            focus=json.loads(row["focus_json"]),
            queries=json.loads(row["queries_json"]),
            rationale=row["rationale"],
            gaps=json.loads(row["gaps_json"] or "[]"),
            source_classes=json.loads(row["source_classes_json"] or "[]"),
        )

    def pending_queries(self, run_id: str, round_no: int) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT query FROM queries WHERE run_id=? AND round_no=? AND status!='completed' ORDER BY id",
                (run_id, round_no),
            ).fetchall()
        return [row["query"] for row in rows]

    def queries_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM queries WHERE run_id=? ORDER BY round_no,id", (run_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def completed_queries(self, run_id: str) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT query FROM queries WHERE run_id=? AND status='completed' ORDER BY id", (run_id,)
            ).fetchall()
        return [row["query"] for row in rows]

    def complete_query(self, run_id: str, round_no: int, query: str, error: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE queries SET status=?,completed_at=?,error=? WHERE run_id=? AND round_no=? AND query=?",
                ("failed" if error else "completed", utc_now(), error, run_id, round_no, query),
            )

    # ---------- sources / snapshots ----------
    def add_search_result(self, run_id: str, query: str, rank: int, result: SearchResult) -> int:
        from urllib.parse import urlsplit

        canonical = canonicalize_url(result.url)
        domain = (urlsplit(canonical).hostname or "").lower()
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO sources(canonical_url,url,title,domain,first_seen_at) VALUES (?,?,?,?,?)
                   ON CONFLICT(canonical_url) DO UPDATE SET
                     title=CASE WHEN excluded.title!='' THEN excluded.title ELSE sources.title END,
                     url=excluded.url""",
                (canonical, result.url, result.title, domain, now),
            )
            source_id = int(
                conn.execute("SELECT id FROM sources WHERE canonical_url=?", (canonical,)).fetchone()["id"]
            )
            published_at = result.published_at
            if not published_at:
                metadata_row = conn.execute(
                    """SELECT value_text FROM observations
                       WHERE source_id=? AND kind='page_metadata' ORDER BY id DESC LIMIT 1""",
                    (source_id,),
                ).fetchone()
                if metadata_row:
                    try:
                        metadata = json.loads(metadata_row["value_text"] or "{}")
                    except (TypeError, ValueError):
                        metadata = {}
                    if isinstance(metadata, dict):
                        published_at = metadata_published_at(metadata)
            conn.execute(
                """INSERT OR IGNORE INTO run_sources
                   (run_id,source_id,search_query,rank,snippet,engine,category,published_at,raw_json,discovered_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    source_id,
                    query,
                    rank,
                    result.snippet,
                    result.engine,
                    result.category,
                    published_at,
                    json.dumps(result.raw, ensure_ascii=False, default=str),
                    now,
                ),
            )
        return source_id

    def set_run_source_published_at(self, run_id: str, source_id: int, value: str | None) -> None:
        if not value:
            return
        with self.connect() as conn:
            conn.execute(
                """UPDATE run_sources SET published_at=?
                   WHERE run_id=? AND source_id=? AND (published_at IS NULL OR published_at='')""",
                (value[:100], run_id, source_id),
            )

    def attach_crawled_source(
        self, run_id: str, url: str, parent_source_id: int | None, relation: str = "link"
    ) -> int:
        from urllib.parse import urlsplit

        canonical = canonicalize_url(url)
        domain = (urlsplit(canonical).hostname or "").lower()
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sources(canonical_url,url,title,domain,first_seen_at) VALUES (?,?,?,?,?)",
                (canonical, url, "", domain, now),
            )
            sid = int(
                conn.execute("SELECT id FROM sources WHERE canonical_url=?", (canonical,)).fetchone()["id"]
            )
            conn.execute(
                """INSERT OR IGNORE INTO run_sources
                   (run_id,source_id,search_query,rank,snippet,engine,category,raw_json,discovered_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (run_id, sid, f"frontier:{parent_source_id or 0}", 0, "", "frontier", relation, "{}", now),
            )
        return sid

    def save_snapshot(
        self,
        *,
        source_id: int,
        final_url: str,
        status_code: int,
        content_type: str,
        content_hash: str,
        raw: bytes,
        text: str,
        extracted_title: str,
        simhash: str = "",
    ) -> None:
        folder = self.data_dir / "sources" / f"{source_id:08d}"
        folder.mkdir(parents=True, exist_ok=True)
        raw_path = folder / f"{content_hash}.raw.gz"
        text_path = folder / f"{content_hash}.txt"
        if not raw_path.exists():
            raw_path.write_bytes(gzip.compress(raw, compresslevel=6))
        if not text_path.exists():
            text_path.write_text(text, encoding="utf-8")
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO snapshots
                   (source_id,fetched_at,final_url,status_code,content_type,content_hash,raw_path,text_path,extracted_title,simhash)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    source_id,
                    utc_now(),
                    final_url,
                    status_code,
                    content_type,
                    content_hash,
                    str(raw_path),
                    str(text_path),
                    extracted_title,
                    simhash,
                ),
            )
            if extracted_title:
                conn.execute(
                    "UPDATE sources SET title=CASE WHEN title='' THEN ? ELSE title END WHERE id=?",
                    (extracted_title, source_id),
                )

    def latest_snapshot(self, source_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE source_id=? ORDER BY fetched_at DESC LIMIT 1", (source_id,)
            ).fetchone()
        return dict(row) if row else None

    def snapshot_text(self, source_id: int) -> str:
        snap = self.latest_snapshot(source_id)
        if not snap or not snap.get("text_path"):
            return ""
        try:
            return Path(snap["text_path"]).read_text(encoding="utf-8")
        except OSError:
            return ""

    def snapshot_raw(self, source_id: int) -> bytes:
        snap = self.latest_snapshot(source_id)
        if not snap or not snap.get("raw_path"):
            return b""
        try:
            return gzip.decompress(Path(snap["raw_path"]).read_bytes())
        except OSError:
            return b""

    def sources_for_run(self, run_id: str, limit: int = 500) -> list[SourceView]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT s.*,
                          (SELECT r2.rank FROM run_sources r2 WHERE r2.run_id=rs.run_id AND r2.source_id=s.id ORDER BY r2.rank,r2.discovered_at LIMIT 1) rank,
                          (SELECT r2.search_query FROM run_sources r2 WHERE r2.run_id=rs.run_id AND r2.source_id=s.id ORDER BY r2.rank,r2.discovered_at LIMIT 1) search_query,
                          (SELECT r2.engine FROM run_sources r2 WHERE r2.run_id=rs.run_id AND r2.source_id=s.id ORDER BY r2.rank,r2.discovered_at LIMIT 1) engine,
                          (SELECT r2.category FROM run_sources r2 WHERE r2.run_id=rs.run_id AND r2.source_id=s.id ORDER BY r2.rank,r2.discovered_at LIMIT 1) category,
                          (SELECT r2.snippet FROM run_sources r2 WHERE r2.run_id=rs.run_id AND r2.source_id=s.id ORDER BY r2.rank,r2.discovered_at LIMIT 1) snippet,
                          (SELECT r2.published_at FROM run_sources r2 WHERE r2.run_id=rs.run_id AND r2.source_id=s.id ORDER BY r2.rank,r2.discovered_at LIMIT 1) published_at,
                          (SELECT r2.discovered_at FROM run_sources r2 WHERE r2.run_id=rs.run_id AND r2.source_id=s.id ORDER BY r2.rank,r2.discovered_at LIMIT 1) discovered_at,
                          (SELECT text_path FROM snapshots x WHERE x.source_id=s.id ORDER BY fetched_at DESC LIMIT 1) text_path,
                          a.relevance,a.importance,a.novelty,a.authority,a.duplicate_of,a.family_key
                   FROM sources s JOIN run_sources rs ON rs.source_id=s.id
                   LEFT JOIN source_analysis a ON a.source_id=s.id AND a.run_id=rs.run_id
                   WHERE rs.run_id=? GROUP BY s.id ORDER BY COALESCE(a.importance,0) DESC, rank, s.id LIMIT ?""",
                (run_id, limit),
            ).fetchall()
        out: list[SourceView] = []
        for row in rows:
            excerpt = ""
            if row["text_path"]:
                with suppress(OSError):
                    excerpt = Path(row["text_path"]).read_text(encoding="utf-8")[:6000]
            out.append(
                SourceView(
                    id=row["id"],
                    url=row["url"],
                    canonical_url=row["canonical_url"],
                    title=row["title"],
                    domain=row["domain"],
                    snippet=row["snippet"] or "",
                    search_query=row["search_query"] or "",
                    rank=row["rank"] or 0,
                    engine=row["engine"] or "unknown",
                    category=row["category"] or "web",
                    published_at=row["published_at"],
                    discovered_at=row["discovered_at"] or utc_now(),
                    fetched=bool(row["text_path"]),
                    text_excerpt=excerpt,
                    relevance=row["relevance"],
                    importance=row["importance"],
                    novelty=row["novelty"],
                    authority=row["authority"],
                    duplicate_of=row["duplicate_of"],
                    family_key=row["family_key"] or "",
                )
            )
        return out

    def source_discoveries(self, run_id: str, source_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT search_query,rank,engine,category,published_at,discovered_at FROM run_sources WHERE run_id=? AND source_id=? ORDER BY discovered_at,rank",
                (run_id, source_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def discoveries_for_run(self, run_id: str, limit: int = 5000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT rs.*,s.url,s.canonical_url,s.title,s.domain FROM run_sources rs JOIN sources s ON s.id=rs.source_id
                   WHERE rs.run_id=? ORDER BY rs.discovered_at,rs.rank LIMIT ?""",
                (run_id, limit),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            try:
                item["raw"] = json.loads(item.pop("raw_json"))
            except (json.JSONDecodeError, TypeError):
                item["raw"] = {}
                item.pop("raw_json", None)
            out.append(item)
        return out

    # ---------- evidence / triage ----------
    def save_analysis(
        self,
        run_id: str,
        source_id: int,
        result: TriageResult,
        *,
        family_key: str = "",
        duplicate_of: int | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO source_analysis(run_id,source_id,relevance,importance,novelty,authority,rationale,
                                                topics_json,leads_json,family_key,duplicate_of,analyzed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(run_id,source_id) DO UPDATE SET
                     relevance=excluded.relevance,importance=excluded.importance,novelty=excluded.novelty,
                     authority=excluded.authority,rationale=excluded.rationale,topics_json=excluded.topics_json,
                     leads_json=excluded.leads_json,family_key=excluded.family_key,duplicate_of=excluded.duplicate_of,
                     analyzed_at=excluded.analyzed_at""",
                (
                    run_id,
                    source_id,
                    result.relevance,
                    result.importance,
                    result.novelty,
                    result.authority,
                    result.rationale,
                    json.dumps(result.topics, ensure_ascii=False),
                    json.dumps(result.leads, ensure_ascii=False),
                    family_key,
                    duplicate_of,
                    utc_now(),
                ),
            )

    def analysis_for_source(self, run_id: str, source_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM source_analysis WHERE run_id=? AND source_id=?", (run_id, source_id)
            ).fetchone()
        return dict(row) if row else None

    def analyzed_source_ids(self, run_id: str) -> set[int]:
        with self.connect() as conn:
            rows = conn.execute("SELECT source_id FROM source_analysis WHERE run_id=?", (run_id,)).fetchall()
        return {int(row["source_id"]) for row in rows}

    def find_near_duplicate(
        self, run_id: str, source_id: int, simhash_value: str, max_distance: int = 3
    ) -> int | None:
        if not simhash_value:
            return None
        try:
            target = int(simhash_value, 16)
        except ValueError:
            return None
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT DISTINCT s.id,x.simhash FROM sources s JOIN run_sources rs ON rs.source_id=s.id
                   JOIN snapshots x ON x.source_id=s.id WHERE rs.run_id=? AND s.id<>? AND x.simhash<>''""",
                (run_id, source_id),
            ).fetchall()
        best: tuple[int, int] | None = None
        for row in rows:
            try:
                dist = (target ^ int(row["simhash"], 16)).bit_count()
            except ValueError:
                continue
            if dist <= max_distance and (best is None or dist < best[1]):
                best = (int(row["id"]), dist)
        return best[0] if best else None

    def add_claim(
        self,
        run_id: str,
        source_id: int,
        *,
        claim_text: str,
        subject: str,
        predicate: str,
        object_text: str,
        observed_at: str | None,
        confidence: float,
        quote: str,
        char_start: int | None,
        char_end: int | None,
        verified_span: bool,
        importance: float = 0,
        rarity: float = 0,
        sensitivity: str = "public",
    ) -> int:
        with self.connect() as conn:
            snapshot = conn.execute(
                "SELECT id FROM snapshots WHERE source_id=? ORDER BY fetched_at DESC LIMIT 1",
                (source_id,),
            ).fetchone()
            snapshot_id = int(snapshot["id"]) if snapshot else None
            cur = conn.execute(
                """INSERT INTO claims(run_id,source_id,claim_text,subject,predicate,object_text,observed_at,
                   confidence,status,created_at,snapshot_id,importance,rarity,sensitivity)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    source_id,
                    claim_text,
                    subject,
                    predicate,
                    object_text,
                    observed_at,
                    confidence,
                    "grounded" if verified_span else "unverified_span",
                    utc_now(),
                    snapshot_id,
                    min(100, max(0, importance)),
                    min(100, max(0, rarity)),
                    sensitivity,
                ),
            )
            claim_id = int(cur.lastrowid)
            conn.execute(
                """INSERT INTO evidence(claim_id,source_id,quote,char_start,char_end,verified_span,created_at,snapshot_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    claim_id,
                    source_id,
                    quote,
                    char_start,
                    char_end,
                    1 if verified_span else 0,
                    utc_now(),
                    snapshot_id,
                ),
            )
        self.add_research_edge(
            run_id,
            from_type="source",
            from_id=source_id,
            relation="supports_claim",
            to_type="claim",
            to_id=claim_id,
            metadata={"snapshot_id": snapshot_id, "verified_span": verified_span},
        )
        return claim_id

    def claims_for_run(self, run_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT c.*,e.quote,e.char_start,e.char_end,e.verified_span,s.url,s.title,s.domain
                   FROM claims c LEFT JOIN evidence e ON e.claim_id=c.id JOIN sources s ON s.id=c.source_id
                   WHERE c.run_id=? ORDER BY c.confidence DESC,c.id LIMIT ?""",
                (run_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_claim_assessment(
        self,
        run_id: str,
        claim_id: int,
        *,
        verdict: str,
        confidence: float,
        supporting_claim_ids: list[int] | None = None,
        conflicting_claim_ids: list[int] | None = None,
        rationale: str = "",
    ) -> None:
        allowed = {"corroborated", "single_source", "contested", "insufficient"}
        if verdict not in allowed:
            raise ValueError(f"invalid claim verdict: {verdict}")
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO claim_assessments
                   (claim_id,run_id,verdict,confidence,supporting_claim_ids_json,
                    conflicting_claim_ids_json,rationale,assessed_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(claim_id) DO UPDATE SET verdict=excluded.verdict,
                   confidence=excluded.confidence,
                   supporting_claim_ids_json=excluded.supporting_claim_ids_json,
                   conflicting_claim_ids_json=excluded.conflicting_claim_ids_json,
                   rationale=excluded.rationale,assessed_at=excluded.assessed_at""",
                (
                    claim_id,
                    run_id,
                    verdict,
                    min(1.0, max(0.0, float(confidence))),
                    json.dumps(sorted(set(supporting_claim_ids or []))),
                    json.dumps(sorted(set(conflicting_claim_ids or []))),
                    rationale[:2000],
                    utc_now(),
                ),
            )

    def claim_assessments_for_run(self, run_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM claim_assessments WHERE run_id=? ORDER BY claim_id LIMIT ?",
                (run_id, limit),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["supporting_claim_ids"] = json.loads(item.pop("supporting_claim_ids_json") or "[]")
            item["conflicting_claim_ids"] = json.loads(item.pop("conflicting_claim_ids_json") or "[]")
            out.append(item)
        return out

    # ---------- frontier ----------
    def add_frontier(
        self,
        run_id: str,
        url: str,
        *,
        parent_source_id: int | None,
        anchor: str,
        relation: str,
        depth: int,
        score: float,
    ) -> bool:
        from urllib.parse import urlsplit

        canonical = canonicalize_url(url)
        domain = (urlsplit(canonical).hostname or "").lower()
        if not canonical.startswith(("http://", "https://")) or not domain:
            return False
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO frontier(run_id,canonical_url,url,parent_source_id,anchor,relation,depth,score,status,domain,discovered_at)
                   VALUES (?,?,?,?,?,?,?,?, 'pending', ?,?)""",
                (
                    run_id,
                    canonical,
                    url,
                    parent_source_id,
                    anchor[:500],
                    relation,
                    depth,
                    score,
                    domain,
                    utc_now(),
                ),
            )
        return bool(cur.rowcount)

    def lease_frontier(
        self, run_id: str, *, max_depth: int, min_score: float, per_domain_limit: int, limit: int
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT f.* FROM frontier f
                   WHERE f.run_id=? AND f.status='pending' AND f.depth<=? AND f.score>=?
                     AND (SELECT COUNT(*) FROM frontier d WHERE d.run_id=f.run_id AND d.domain=f.domain AND d.status='completed') < ?
                   ORDER BY f.score DESC,f.depth ASC,f.id ASC LIMIT ?""",
                (run_id, max_depth, min_score, per_domain_limit, limit),
            ).fetchall()
            ids = [int(row["id"]) for row in rows]
            if ids:
                conn.executemany(
                    "UPDATE frontier SET status='leased',leased_at=? WHERE id=?",
                    [(utc_now(), i) for i in ids],
                )
        return [dict(row) for row in rows]

    def complete_frontier(self, frontier_id: int, error: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE frontier SET status=?,completed_at=?,error=? WHERE id=?",
                ("failed" if error else "completed", utc_now(), error, frontier_id),
            )

    def frontier_for_run(self, run_id: str, limit: int = 5000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM frontier WHERE run_id=? ORDER BY score DESC,id LIMIT ?",
                (run_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def recover_frontier_leases(self, run_id: str) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE frontier SET status='pending',leased_at=NULL WHERE run_id=? AND status='leased'",
                (run_id,),
            )
        return int(cur.rowcount)

    def frontier_stats(self, run_id: str) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT status,COUNT(*) n FROM frontier WHERE run_id=? GROUP BY status", (run_id,)
            ).fetchall()
        return {row["status"]: int(row["n"]) for row in rows}

    def domain_checked(self, run_id: str, domain: str, field: str) -> bool:
        if field not in {"sitemap_checked", "robots_checked"}:
            raise ValueError(field)
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT {field} FROM domain_state WHERE run_id=? AND domain=?", (run_id, domain)
            ).fetchone()
        return bool(row and row[field])

    def mark_domain_checked(self, run_id: str, domain: str, field: str) -> None:
        if field not in {"sitemap_checked", "robots_checked"}:
            raise ValueError(field)
        with self.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO domain_state(run_id,domain) VALUES (?,?)", (run_id, domain))
            conn.execute(f"UPDATE domain_state SET {field}=1 WHERE run_id=? AND domain=?", (run_id, domain))

    def source_stage_state(self, run_id: str, source_id: int, stage: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM source_stage_state WHERE run_id=? AND source_id=? AND stage=?",
                (run_id, source_id, stage),
            ).fetchone()
        return dict(row) if row else None

    def mark_source_stage(
        self,
        run_id: str,
        source_id: int,
        stage: str,
        *,
        status: str = "done",
        result_count: int = 0,
        error: str = "",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO source_stage_state(run_id,source_id,stage,status,result_count,last_error,checked_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(run_id,source_id,stage) DO UPDATE SET
                   status=excluded.status,result_count=excluded.result_count,last_error=excluded.last_error,checked_at=excluded.checked_at""",
                (run_id, source_id, stage, status, int(result_count), error[:1000], utc_now()),
            )

    # ---------- Stage 4 archives / citations ----------
    def add_archive_capture(
        self,
        run_id: str,
        source_id: int,
        *,
        engine: str,
        captured_at: str,
        capture_url: str,
        mime: str = "",
        status_code: int | None = None,
        digest: str = "",
        raw: dict[str, Any] | None = None,
    ) -> int:
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO archive_captures(run_id,source_id,engine,captured_at,capture_url,mime,status_code,digest,raw_json,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    source_id,
                    engine,
                    captured_at,
                    capture_url,
                    mime,
                    status_code,
                    digest,
                    json.dumps(raw or {}, ensure_ascii=False, default=str),
                    utc_now(),
                ),
            )
            row = conn.execute(
                "SELECT id FROM archive_captures WHERE run_id=? AND source_id=? AND engine=? AND captured_at=? AND capture_url=?",
                (run_id, source_id, engine, captured_at, capture_url),
            ).fetchone()
        assert row is not None
        return int(row["id"])

    def save_archive_content(self, capture_id: int, *, raw: bytes, text: str, content_hash: str) -> None:
        raw_rel = Path("artifacts") / "archives" / f"capture-{capture_id}.raw.gz"
        text_rel = Path("artifacts") / "archives" / f"capture-{capture_id}.txt.gz"
        (self.data_dir / raw_rel).parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(self.data_dir / raw_rel, "wb") as fh:
            fh.write(raw)
        with gzip.open(self.data_dir / text_rel, "wt", encoding="utf-8") as fh:
            fh.write(text)
        with self.connect() as conn:
            conn.execute(
                "UPDATE archive_captures SET raw_path=?,text_path=?,content_hash=? WHERE id=?",
                (str(raw_rel), str(text_rel), content_hash, capture_id),
            )

    def archive_captures_for_run(self, run_id: str, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM archive_captures WHERE run_id=? ORDER BY captured_at DESC LIMIT ?",
                (run_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def archive_text(self, capture_id: int) -> str:
        with self.connect() as conn:
            row = conn.execute("SELECT text_path FROM archive_captures WHERE id=?", (capture_id,)).fetchone()
        if not row or not row["text_path"]:
            return ""
        try:
            with gzip.open(self.data_dir / row["text_path"], "rt", encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return ""

    def add_citation(
        self,
        run_id: str,
        source_id: int,
        *,
        target_url: str,
        kind: str,
        label: str,
        target_source_id: int | None = None,
    ) -> int:
        target_url = canonicalize_url(target_url)
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO citations(run_id,source_id,target_url,kind,label,target_source_id,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (run_id, source_id, target_url, kind, label, target_source_id, utc_now()),
            )
            if target_source_id is not None:
                conn.execute(
                    "UPDATE citations SET target_source_id=? WHERE run_id=? AND source_id=? AND target_url=?",
                    (target_source_id, run_id, source_id, target_url),
                )
            row = conn.execute(
                "SELECT id FROM citations WHERE run_id=? AND source_id=? AND target_url=?",
                (run_id, source_id, target_url),
            ).fetchone()
        assert row is not None
        return int(row["id"])

    def citations_for_run(self, run_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM citations WHERE run_id=? ORDER BY id LIMIT ?", (run_id, limit)
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------- Stage 5 foundation: entities, relationships, timeline, research graph ----------
    def upsert_entity(
        self,
        run_id: str,
        *,
        name: str,
        entity_type: str = "unknown",
        description: str = "",
        confidence: float = 0.5,
        aliases: list[str] | None = None,
    ) -> int:
        clean = " ".join(name.split()).strip()
        if not clean:
            raise ValueError("empty entity name")
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO entities(run_id,canonical_name,entity_type,description,confidence,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?) ON CONFLICT(run_id,canonical_name,entity_type) DO UPDATE SET
                   description=CASE WHEN excluded.description!='' THEN excluded.description ELSE entities.description END,
                   confidence=MAX(entities.confidence,excluded.confidence),updated_at=excluded.updated_at""",
                (run_id, clean, entity_type or "unknown", description, confidence, now, now),
            )
            row = conn.execute(
                "SELECT id FROM entities WHERE run_id=? AND canonical_name=? AND entity_type=?",
                (run_id, clean, entity_type or "unknown"),
            ).fetchone()
            assert row is not None
            eid = int(row["id"])
            for alias in aliases or []:
                alias = " ".join(alias.split()).strip()
                if alias:
                    conn.execute(
                        "INSERT OR IGNORE INTO entity_aliases(entity_id,alias,created_at) VALUES (?,?,?)",
                        (eid, alias, now),
                    )
        return eid

    def add_relationship(
        self,
        run_id: str,
        *,
        source_entity_id: int,
        predicate: str,
        target_entity_id: int | None = None,
        target_text: str = "",
        claim_id: int | None = None,
        source_id: int | None = None,
        confidence: float = 0.5,
    ) -> int:
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO relationships(run_id,source_entity_id,predicate,target_entity_id,target_text,claim_id,source_id,confidence,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    source_entity_id,
                    predicate,
                    target_entity_id,
                    target_text,
                    claim_id,
                    source_id,
                    confidence,
                    utc_now(),
                ),
            )
            row = conn.execute(
                """SELECT id FROM relationships WHERE run_id=? AND source_entity_id=? AND predicate=?
                   AND target_entity_id IS ? AND target_text=? AND claim_id IS ?""",
                (run_id, source_entity_id, predicate, target_entity_id, target_text, claim_id),
            ).fetchone()
        return int(row["id"]) if row else 0

    def add_timeline_event(
        self,
        run_id: str,
        *,
        event_time: str,
        label: str,
        entity_id: int | None = None,
        claim_id: int | None = None,
        source_id: int | None = None,
        confidence: float = 0.5,
    ) -> int:
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO timeline_events(run_id,event_time,label,entity_id,claim_id,source_id,confidence,created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (run_id, event_time, label, entity_id, claim_id, source_id, confidence, utc_now()),
            )
            row = conn.execute(
                "SELECT id FROM timeline_events WHERE run_id=? AND event_time=? AND label=? AND claim_id IS ?",
                (run_id, event_time, label, claim_id),
            ).fetchone()
        return int(row["id"]) if row else 0

    def add_research_edge(
        self,
        run_id: str,
        *,
        from_type: str,
        from_id: str | int,
        relation: str,
        to_type: str,
        to_id: str | int,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO research_edges(run_id,from_type,from_id,relation,to_type,to_id,metadata_json,created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    from_type,
                    str(from_id),
                    relation,
                    to_type,
                    str(to_id),
                    json.dumps(metadata or {}, ensure_ascii=False, default=str),
                    utc_now(),
                ),
            )
            row = conn.execute(
                "SELECT id FROM research_edges WHERE run_id=? AND from_type=? AND from_id=? AND relation=? AND to_type=? AND to_id=?",
                (run_id, from_type, str(from_id), relation, to_type, str(to_id)),
            ).fetchone()
        return int(row["id"]) if row else 0

    def entities_for_run(self, run_id: str, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM entities WHERE run_id=? ORDER BY confidence DESC,canonical_name LIMIT ?",
                (run_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def entity_aliases_for_run(self, run_id: str) -> dict[int, list[str]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT a.entity_id,a.alias FROM entity_aliases a
                   JOIN entities e ON e.id=a.entity_id WHERE e.run_id=? ORDER BY a.entity_id,a.alias""",
                (run_id,),
            ).fetchall()
        aliases: dict[int, list[str]] = {}
        for row in rows:
            aliases.setdefault(int(row["entity_id"]), []).append(str(row["alias"]))
        return aliases

    def save_identity_hypothesis(
        self,
        run_id: str,
        left_entity_id: int,
        right_entity_id: int,
        *,
        verdict: str,
        confidence: float,
        evidence_claim_ids: list[int] | None = None,
        rationale: str = "",
    ) -> None:
        left, right = sorted((int(left_entity_id), int(right_entity_id)))
        if left == right or verdict not in {"same", "different", "uncertain"}:
            raise ValueError("invalid identity hypothesis")
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO identity_hypotheses
                   (run_id,left_entity_id,right_entity_id,verdict,confidence,evidence_claim_ids_json,rationale,assessed_at)
                   VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(run_id,left_entity_id,right_entity_id) DO UPDATE SET
                   verdict=excluded.verdict,confidence=excluded.confidence,
                   evidence_claim_ids_json=excluded.evidence_claim_ids_json,rationale=excluded.rationale,
                   assessed_at=excluded.assessed_at""",
                (
                    run_id,
                    left,
                    right,
                    verdict,
                    min(1.0, max(0.0, float(confidence))),
                    json.dumps(sorted(set(evidence_claim_ids or []))),
                    rationale[:2000],
                    utc_now(),
                ),
            )

    def identity_hypotheses_for_run(self, run_id: str, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT h.*,l.canonical_name left_name,r.canonical_name right_name
                   FROM identity_hypotheses h JOIN entities l ON l.id=h.left_entity_id
                   JOIN entities r ON r.id=h.right_entity_id WHERE h.run_id=?
                   ORDER BY h.confidence DESC,h.id LIMIT ?""",
                (run_id, limit),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["evidence_claim_ids"] = json.loads(item.pop("evidence_claim_ids_json") or "[]")
            out.append(item)
        return out

    def relationships_for_run(self, run_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM relationships WHERE run_id=? ORDER BY id LIMIT ?", (run_id, limit)
            ).fetchall()
        return [dict(row) for row in rows]

    def timeline_for_run(self, run_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM timeline_events WHERE run_id=? ORDER BY event_time,id LIMIT ?", (run_id, limit)
            ).fetchall()
        return [dict(row) for row in rows]

    def research_edges_for_run(self, run_id: str, limit: int = 5000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM research_edges WHERE run_id=? ORDER BY id LIMIT ?", (run_id, limit)
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------- durable work queue / artifacts ----------
    def enqueue_task(
        self,
        run_id: str,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        dedupe_key: str,
        priority: int = 100,
        max_attempts: int = 3,
        depends_on: list[str] | None = None,
    ) -> str:
        """Create idempotent work that can survive process restarts."""
        now = utc_now()
        task_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO research_tasks
                   (id,run_id,kind,payload_json,state,priority,attempt_count,max_attempts,
                    available_at,dedupe_key,created_at,updated_at)
                   VALUES (?,?,?,?,'pending',?,0,?,?,?,?,?)""",
                (
                    task_id,
                    run_id,
                    kind,
                    json.dumps(payload or {}, ensure_ascii=False, default=str),
                    priority,
                    max_attempts,
                    now,
                    dedupe_key,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM research_tasks WHERE run_id=? AND dedupe_key=?",
                (run_id, dedupe_key),
            ).fetchone()
            task_id = str(row["id"])
            for dependency in depends_on or []:
                conn.execute(
                    "INSERT OR IGNORE INTO research_task_dependencies(task_id,depends_on_task_id) VALUES (?,?)",
                    (task_id, dependency),
                )
        self.add_research_edge(
            run_id,
            from_type="run",
            from_id=run_id,
            relation="scheduled",
            to_type="task",
            to_id=task_id,
            metadata={"kind": kind, "dedupe_key": dedupe_key},
        )
        return task_id

    def recover_expired_tasks(self, run_id: str) -> int:
        now = utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                """UPDATE research_tasks
                   SET state='pending',lease_owner=NULL,lease_expires_at=NULL,updated_at=?
                   WHERE run_id=? AND state='leased' AND lease_expires_at IS NOT NULL AND lease_expires_at<=?""",
                (now, run_id, now),
            )
        return int(cur.rowcount)

    def lease_tasks(
        self,
        run_id: str,
        worker_id: str,
        *,
        limit: int = 1,
        lease_seconds: int = 300,
        kinds: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        now = utc_now()
        expires = (datetime.now(UTC) + timedelta(seconds=max(1, lease_seconds))).isoformat()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            params: list[Any] = [run_id, now]
            kind_filter = ""
            if kinds:
                placeholders = ",".join("?" for _ in kinds)
                kind_filter = f" AND t.kind IN ({placeholders})"
                params.extend(sorted(kinds))
            params.append(max(1, limit))
            rows = conn.execute(
                f"""SELECT t.id FROM research_tasks t
                    WHERE t.run_id=? AND t.state IN ('pending','retry') AND t.available_at<=?
                      {kind_filter}
                      AND NOT EXISTS (
                        SELECT 1 FROM research_task_dependencies d
                        JOIN research_tasks parent ON parent.id=d.depends_on_task_id
                        WHERE d.task_id=t.id AND parent.state!='completed'
                      )
                    ORDER BY t.priority,t.created_at LIMIT ?""",
                params,
            ).fetchall()
            ids = [str(row["id"]) for row in rows]
            for task_id in ids:
                conn.execute(
                    """UPDATE research_tasks SET state='leased',lease_owner=?,lease_expires_at=?,
                       attempt_count=attempt_count+1,updated_at=?
                       WHERE id=? AND state IN ('pending','retry')""",
                    (worker_id, expires, now, task_id),
                )
            leased = []
            for task_id in ids:
                row = conn.execute("SELECT * FROM research_tasks WHERE id=?", (task_id,)).fetchone()
                if row and row["lease_owner"] == worker_id:
                    item = dict(row)
                    item["payload"] = json.loads(item.pop("payload_json") or "{}")
                    leased.append(item)
        return leased

    def complete_task(self, task_id: str, result: dict[str, Any] | None = None) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                """UPDATE research_tasks SET state='completed',result_json=?,last_error=NULL,
                   lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE id=? AND state='leased'""",
                (json.dumps(result or {}, ensure_ascii=False, default=str), utc_now(), task_id),
            )
        return bool(cur.rowcount)

    def release_task(self, task_id: str) -> bool:
        """Return a cooperative pause/cancellation lease to the queue without consuming an attempt."""
        with self.connect() as conn:
            cur = conn.execute(
                """UPDATE research_tasks SET state='pending',attempt_count=MAX(0,attempt_count-1),
                   lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE id=? AND state='leased'""",
                (utc_now(), task_id),
            )
        return bool(cur.rowcount)

    def fail_task(self, task_id: str, error: str, *, retry_delay_seconds: int = 30) -> str:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT attempt_count,max_attempts FROM research_tasks WHERE id=?",
                (task_id,),
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown task: {task_id}")
            state = "failed" if int(row["attempt_count"]) >= int(row["max_attempts"]) else "retry"
            available = (datetime.now(UTC) + timedelta(seconds=max(0, retry_delay_seconds))).isoformat()
            conn.execute(
                """UPDATE research_tasks SET state=?,available_at=?,last_error=?,lease_owner=NULL,
                   lease_expires_at=NULL,updated_at=? WHERE id=?""",
                (state, available, error[:2000], utc_now(), task_id),
            )
        return state

    def tasks_for_run(self, run_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM research_tasks WHERE run_id=? ORDER BY created_at LIMIT ?",
                (run_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def task_stats(self, run_id: str) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT state,COUNT(*) count FROM research_tasks WHERE run_id=? GROUP BY state",
                (run_id,),
            ).fetchall()
        return {str(row["state"]): int(row["count"]) for row in rows}

    def save_artifact(
        self,
        run_id: str,
        data: bytes,
        *,
        media_type: str,
        source_id: int | None = None,
        snapshot_id: int | None = None,
        sensitivity: str = "public",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        digest = hashlib.sha256(data).hexdigest()
        artifact_id = f"{run_id}-{digest[:20]}"
        suffix = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "application/pdf": ".pdf",
            "video/mp4": ".mp4",
        }.get(media_type.casefold(), ".bin")
        folder = self.data_dir / "artifacts" / run_id / digest[:2]
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{digest}{suffix}"
        if not path.exists():
            path.write_bytes(data)
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO artifacts
                   (id,run_id,source_id,snapshot_id,sha256,media_type,byte_size,path,sensitivity,metadata_json,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    artifact_id,
                    run_id,
                    source_id,
                    snapshot_id,
                    digest,
                    media_type,
                    len(data),
                    str(path),
                    sensitivity,
                    json.dumps(metadata or {}, ensure_ascii=False, default=str),
                    utc_now(),
                ),
            )
        if source_id is not None:
            self.add_research_edge(
                run_id,
                from_type="source",
                from_id=source_id,
                relation="has_artifact",
                to_type="artifact",
                to_id=artifact_id,
                metadata={"sha256": digest, "media_type": media_type},
            )
        return artifact_id

    def add_observation(
        self,
        run_id: str,
        *,
        kind: str,
        value_text: str,
        source_id: int | None = None,
        snapshot_id: int | None = None,
        artifact_id: str | None = None,
        locator: dict[str, Any] | None = None,
        confidence: float = 0.5,
        importance: float = 0,
        rarity: float = 0,
        sensitivity: str = "public",
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO observations
                   (run_id,source_id,snapshot_id,artifact_id,kind,value_text,locator_json,confidence,
                    importance,rarity,sensitivity,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    source_id,
                    snapshot_id,
                    artifact_id,
                    kind,
                    value_text,
                    json.dumps(locator or {}, ensure_ascii=False, default=str),
                    min(1, max(0, confidence)),
                    min(100, max(0, importance)),
                    min(100, max(0, rarity)),
                    sensitivity,
                    utc_now(),
                ),
            )
        observation_id = int(cur.lastrowid)
        if artifact_id:
            self.add_research_edge(
                run_id,
                from_type="artifact",
                from_id=artifact_id,
                relation="contains_observation",
                to_type="observation",
                to_id=observation_id,
                metadata={"kind": kind, "locator": locator or {}},
            )
        elif source_id is not None:
            self.add_research_edge(
                run_id,
                from_type="source",
                from_id=source_id,
                relation="contains_observation",
                to_type="observation",
                to_id=observation_id,
                metadata={"kind": kind, "locator": locator or {}},
            )
        return observation_id

    def observations_for_run(self, run_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM observations WHERE run_id=?
                   ORDER BY importance DESC,rarity DESC,id LIMIT ?""",
                (run_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def artifacts_for_run(self, run_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM artifacts WHERE run_id=? ORDER BY created_at,id LIMIT ?",
                (run_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_artifact_match(
        self,
        run_id: str,
        left_artifact_id: str,
        right_artifact_id: str,
        *,
        algorithm: str,
        distance: float,
        verdict: str,
    ) -> None:
        left, right = sorted((left_artifact_id, right_artifact_id))
        if left == right:
            return
        with self.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO artifact_matches
                   (run_id,left_artifact_id,right_artifact_id,algorithm,distance,verdict,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (run_id, left, right, algorithm, float(distance), verdict, utc_now()),
            )

    def artifact_matches_for_run(self, run_id: str, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM artifact_matches WHERE run_id=? ORDER BY distance,id LIMIT ?",
                (run_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def artifact_has_vision_observations(self, artifact_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM observations WHERE artifact_id=? AND kind LIKE 'vision:%' LIMIT 1",
                (artifact_id,),
            ).fetchone()
        return row is not None

    def artifact_has_local_media_observations(self, artifact_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM observations WHERE artifact_id=? AND (kind LIKE 'ocr:%' OR kind LIKE 'metadata:%' OR kind IN ('media:phash','media:image_metrics')) LIMIT 1",
                (artifact_id,),
            ).fetchone()
        return row is not None

    def add_media_lead(
        self,
        run_id: str,
        source_id: int,
        *,
        url: str,
        kind: str = "image",
        alt_text: str = "",
        width: int | None = None,
        height: int | None = None,
    ) -> int:
        canonical = canonicalize_url(url)
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO media_leads
                   (run_id,source_id,url,canonical_url,kind,alt_text,width,height,discovered_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (run_id, source_id, url, canonical, kind, alt_text[:500], width, height, utc_now()),
            )
            row = conn.execute(
                "SELECT id FROM media_leads WHERE run_id=? AND source_id=? AND canonical_url=?",
                (run_id, source_id, canonical),
            ).fetchone()
        lead_id = int(row["id"])
        self.add_research_edge(
            run_id,
            from_type="source",
            from_id=source_id,
            relation="references_media",
            to_type="media_lead",
            to_id=lead_id,
            metadata={"url": canonical, "alt": alt_text[:500]},
        )
        return lead_id

    def pending_media_leads(
        self,
        run_id: str,
        *,
        source_ids: list[int],
        per_source: int,
    ) -> list[dict[str, Any]]:
        if not source_ids or per_source <= 0:
            return []
        placeholders = ",".join("?" for _ in source_ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"""SELECT m.* FROM media_leads m
                    WHERE m.run_id=? AND m.status='pending' AND m.source_id IN ({placeholders})
                      AND (SELECT COUNT(*) FROM media_leads x
                           WHERE x.run_id=m.run_id AND x.source_id=m.source_id
                             AND x.status='completed' AND x.id<=m.id) < ?
                    ORDER BY m.source_id,m.id""",
                [run_id, *source_ids, per_source],
            ).fetchall()
        selected: list[dict[str, Any]] = []
        counts: dict[int, int] = {}
        for row in rows:
            source_id = int(row["source_id"])
            if counts.get(source_id, 0) >= per_source:
                continue
            selected.append(dict(row))
            counts[source_id] = counts.get(source_id, 0) + 1
        return selected

    def complete_media_lead(
        self, lead_id: int, *, artifact_id: str | None = None, error: str | None = None
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE media_leads SET status=?,artifact_id=?,last_error=?,completed_at=? WHERE id=?""",
                (
                    "failed" if error else "completed",
                    artifact_id,
                    error[:1000] if error else None,
                    utc_now(),
                    lead_id,
                ),
            )

    def media_leads_for_run(self, run_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM media_leads WHERE run_id=? ORDER BY source_id,id LIMIT ?",
                (run_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------- sessions ----------
    def create_session(self, name: str = "default") -> str:
        sid = uuid.uuid4().hex[:10]
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO sessions(id,name,created_at,updated_at) VALUES (?,?,?,?)",
                (sid, name, now, now),
            )
        return sid

    def latest_session(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        return dict(row) if row else None

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def update_session(self, session_id: str, **fields: Any) -> None:
        allowed = {
            "name",
            "active_run_id",
            "angle",
            "mode",
            "language",
            "shell_enabled",
            "onboarding_complete",
            "metadata_json",
        }
        pairs = [
            (k, int(v) if k in {"shell_enabled", "onboarding_complete"} else v)
            for k, v in fields.items()
            if k in allowed
        ]
        if not pairs:
            return
        pairs.append(("updated_at", utc_now()))
        with self.connect() as conn:
            conn.execute(
                "UPDATE sessions SET " + ",".join(f"{k}=?" for k, _ in pairs) + " WHERE id=?",
                [v for _, v in pairs] + [session_id],
            )

    # ---------- router health ----------
    def router_state(self, table: str, key_column: str, key: str) -> dict[str, Any] | None:
        if table not in {"router_credentials", "router_deployments"} or key_column not in {
            "credential_key",
            "deployment_key",
        }:
            raise ValueError("invalid router state lookup")
        with self.connect() as conn:
            row = conn.execute(f"SELECT * FROM {table} WHERE {key_column}=?", (key,)).fetchone()
        return dict(row) if row else None

    def router_task_state(self, deployment_key: str, task: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM router_task_health WHERE deployment_key=? AND task=?", (deployment_key, task)
            ).fetchone()
        return dict(row) if row else None

    def update_router_credential(
        self,
        credential_key: str,
        provider_id: str,
        credential_id: str,
        *,
        ok: bool,
        cooldown_until: float = 0,
        status_code: int | None = None,
        error: str | None = None,
        latency: float | None = None,
    ) -> None:
        self._update_health(
            "router_credentials",
            "credential_key",
            credential_key,
            {"provider_id": provider_id, "credential_id": credential_id},
            ok=ok,
            cooldown_until=cooldown_until,
            status_code=status_code,
            error=error,
            latency=latency,
        )

    def update_router_deployment(
        self,
        deployment_key: str,
        provider_id: str,
        credential_id: str,
        model_id: str,
        *,
        ok: bool,
        cooldown_until: float = 0,
        error: str | None = None,
        latency: float | None = None,
    ) -> None:
        self._update_health(
            "router_deployments",
            "deployment_key",
            deployment_key,
            {"provider_id": provider_id, "credential_id": credential_id, "model_id": model_id},
            ok=ok,
            cooldown_until=cooldown_until,
            error=error,
            latency=latency,
        )

    def _update_health(
        self,
        table: str,
        key_col: str,
        key: str,
        identity: dict[str, Any],
        *,
        ok: bool,
        cooldown_until: float,
        status_code: int | None = None,
        error: str | None = None,
        latency: float | None = None,
    ) -> None:
        now = utc_now()
        with self.connect() as conn:
            row = conn.execute(f"SELECT * FROM {table} WHERE {key_col}=?", (key,)).fetchone()
            if row is None:
                cols = [
                    key_col,
                    *identity.keys(),
                    "successes",
                    "failures",
                    "consecutive_failures",
                    "cooldown_until",
                    "last_error",
                    "latency_ema",
                    "updated_at",
                ]
                vals = [
                    key,
                    *identity.values(),
                    1 if ok else 0,
                    0 if ok else 1,
                    0 if ok else 1,
                    0 if ok else cooldown_until,
                    None if ok else error,
                    latency,
                    now,
                ]
                if table == "router_credentials":
                    cols.insert(-3, "last_status")
                    vals.insert(-3, status_code)
                conn.execute(
                    f"INSERT INTO {table}({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})", vals
                )
                return
            successes = int(row["successes"]) + (1 if ok else 0)
            failures = int(row["failures"]) + (0 if ok else 1)
            consecutive = 0 if ok else int(row["consecutive_failures"]) + 1
            old_latency = row["latency_ema"]
            ema = (
                latency
                if old_latency is None
                else (float(old_latency) * 0.8 + float(latency or old_latency) * 0.2)
            )
            fields = [
                "successes=?",
                "failures=?",
                "consecutive_failures=?",
                "cooldown_until=?",
                "last_error=?",
                "latency_ema=?",
                "updated_at=?",
            ]
            values: list[Any] = [
                successes,
                failures,
                consecutive,
                0 if ok else cooldown_until,
                None if ok else error,
                ema,
                now,
            ]
            if table == "router_credentials":
                fields.append("last_status=?")
                values.append(status_code)
            values.append(key)
            conn.execute(f"UPDATE {table} SET {','.join(fields)} WHERE {key_col}=?", values)

    def update_router_task(
        self, deployment_key: str, task: str, *, ok: bool, cooldown_until: float = 0, error: str | None = None
    ) -> None:
        now = utc_now()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM router_task_health WHERE deployment_key=? AND task=?", (deployment_key, task)
            ).fetchone()
            if not row:
                conn.execute(
                    """INSERT INTO router_task_health(deployment_key,task,successes,failures,consecutive_failures,cooldown_until,last_error,updated_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        deployment_key,
                        task,
                        1 if ok else 0,
                        0 if ok else 1,
                        0 if ok else 1,
                        0 if ok else cooldown_until,
                        None if ok else error,
                        now,
                    ),
                )
            else:
                conn.execute(
                    """UPDATE router_task_health SET successes=?,failures=?,consecutive_failures=?,cooldown_until=?,last_error=?,updated_at=?
                       WHERE deployment_key=? AND task=?""",
                    (
                        int(row["successes"]) + (1 if ok else 0),
                        int(row["failures"]) + (0 if ok else 1),
                        0 if ok else int(row["consecutive_failures"]) + 1,
                        0 if ok else cooldown_until,
                        None if ok else error,
                        now,
                        deployment_key,
                        task,
                    ),
                )

    def record_router_attempt(
        self,
        *,
        run_id: str | None,
        task: str,
        provider_id: str,
        credential_id: str,
        model_id: str,
        deployment_key: str,
        ok: bool,
        failure_kind: str | None,
        status_code: int | None,
        latency_seconds: float | None,
        message: str | None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        response_id: str = "",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO router_attempts(run_id,task,provider_id,credential_id,model_id,deployment_key,ok,
                                                failure_kind,status_code,latency_seconds,message,created_at,
                                                prompt_tokens,completion_tokens,total_tokens,response_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    task,
                    provider_id,
                    credential_id,
                    model_id,
                    deployment_key,
                    1 if ok else 0,
                    failure_kind,
                    status_code,
                    latency_seconds,
                    message,
                    utc_now(),
                    max(0, int(prompt_tokens)),
                    max(0, int(completion_tokens)),
                    max(0, int(total_tokens)),
                    response_id[:200],
                ),
            )

    def router_attempts(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM router_attempts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def provider_usage(self, *, run_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        where = "WHERE run_id=?" if run_id else ""
        params: tuple[Any, ...] = (run_id,) if run_id else ()
        with self.connect() as conn:
            rows = conn.execute(
                f"""SELECT provider_id, credential_id, model_id,
                            COUNT(*) requests, SUM(ok) successes, SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END) failures,
                            SUM(prompt_tokens) prompt_tokens, SUM(completion_tokens) completion_tokens,
                            SUM(total_tokens) total_tokens, ROUND(AVG(latency_seconds), 3) avg_latency,
                            MIN(created_at) first_at, MAX(created_at) last_at
                     FROM router_attempts {where}
                     GROUP BY provider_id, credential_id, model_id
                     ORDER BY requests DESC, total_tokens DESC LIMIT ?""",
                (*params, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def router_attempt_count(self, run_id: str, *, task: str | None = None) -> int:
        with self.connect() as conn:
            if task:
                row = conn.execute(
                    "SELECT COUNT(*) count FROM router_attempts WHERE run_id=? AND task=?",
                    (run_id, task),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) count FROM router_attempts WHERE run_id=?", (run_id,)
                ).fetchone()
        return int(row["count"] if row else 0)

    def cached_search(self, query: str, limit: int = 8) -> list[SearchResult]:
        """Reuse previously discovered public evidence when live indexes are unavailable."""
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT s.url,s.title,s.domain,rs.snippet,rs.category,rs.published_at,rs.raw_json,
                          MAX(rs.discovered_at) discovered_at
                   FROM sources s JOIN run_sources rs ON rs.source_id=s.id
                   GROUP BY s.id ORDER BY discovered_at DESC LIMIT 1500"""
            ).fetchall()
        scored: list[tuple[float, sqlite3.Row]] = []
        query_terms = words(query)
        for row in rows:
            haystack = f"{row['title']} {row['url']} {row['snippet']}"
            score = lexical_overlap(query, haystack)
            shared_meaningful = {
                term
                for term in query_terms & words(haystack)
                if not term.isdigit() and term not in {"or", "and", "not", "site", "filetype"}
            }
            if score >= 0.20 and shared_meaningful:
                scored.append((score, row))
        scored.sort(key=lambda item: (-item[0], str(item[1]["url"])))
        results: list[SearchResult] = []
        for score, row in scored[:limit]:
            try:
                raw = json.loads(row["raw_json"] or "{}")
            except (TypeError, ValueError):
                raw = {}
            results.append(
                SearchResult(
                    url=str(row["url"]),
                    title=str(row["title"] or ""),
                    snippet=str(row["snippet"] or ""),
                    engine="traceweave-cache",
                    category=str(row["category"] or "web"),
                    published_at=row["published_at"],
                    raw={**raw, "cache_overlap": score},
                )
            )
        return results

    # ---------- events ----------
    def event(self, run_id: str | None, kind: str, message: str, data: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO events(run_id,ts,kind,message,data_json) VALUES (?,?,?,?,?)",
                (run_id, utc_now(), kind, message, json.dumps(data or {}, ensure_ascii=False, default=str)),
            )

    def events_for_run(self, run_id: str, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE run_id=? ORDER BY id DESC LIMIT ?", (run_id, limit)
            ).fetchall()
        out = []
        for row in reversed(rows):
            item = dict(row)
            try:
                item["data"] = json.loads(item.pop("data_json"))
            except Exception:
                item["data"] = {}
            out.append(item)
        return out
