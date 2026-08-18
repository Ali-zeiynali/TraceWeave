from __future__ import annotations

import gzip
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from traceweave.models import Plan, ResearchSpec, SearchResult, SourceView, utc_now
from traceweave.utils import canonicalize_url

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
    UNIQUE(source_id, content_hash)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT REFERENCES runs(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_queries_run_round ON queries(run_id, round_no, status);
CREATE INDEX IF NOT EXISTS idx_run_sources_run ON run_sources(run_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_source ON snapshots(source_id, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, id);
"""


class Storage:
    def __init__(self, db_path: Path, data_dir: Path):
        self.db_path = Path(db_path)
        self.data_dir = Path(data_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "sources").mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def create_run(self, spec: ResearchSpec) -> str:
        run_id = uuid.uuid4().hex[:12]
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO runs
                   (id, topic, angle, mode, language, status, created_at, updated_at,
                    current_round, max_rounds, max_results_per_query, fetch_top_per_query)
                   VALUES (?, ?, ?, ?, ?, 'created', ?, ?, 0, ?, ?, ?)""",
                (
                    run_id, spec.topic, spec.angle, spec.mode, spec.language, now, now,
                    spec.resolved_rounds(), spec.max_results_per_query, spec.fetch_top_per_query,
                ),
            )
        return run_id

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def latest_run(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def run_spec(self, run_id: str) -> ResearchSpec:
        row = self.get_run(run_id)
        if not row:
            raise KeyError(f"Unknown run: {run_id}")
        return ResearchSpec(
            topic=row["topic"], angle=row["angle"], mode=row["mode"], language=row["language"],
            max_rounds=row["max_rounds"], max_results_per_query=row["max_results_per_query"],
            fetch_top_per_query=row["fetch_top_per_query"],
        )

    def update_run(self, run_id: str, **fields: Any) -> None:
        allowed = {"status", "current_round", "last_error", "final_summary"}
        pairs = [(k, v) for k, v in fields.items() if k in allowed]
        if not pairs:
            return
        pairs.append(("updated_at", utc_now()))
        sql = "UPDATE runs SET " + ", ".join(f"{k} = ?" for k, _ in pairs) + " WHERE id = ?"
        values = [v for _, v in pairs] + [run_id]
        with self.connect() as conn:
            conn.execute(sql, values)

    def save_plan(self, run_id: str, round_no: int, plan: Plan) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO plans(run_id, round_no, objective, focus_json, queries_json, rationale, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id, round_no) DO UPDATE SET
                     objective=excluded.objective, focus_json=excluded.focus_json,
                     queries_json=excluded.queries_json, rationale=excluded.rationale""",
                (
                    run_id, round_no, plan.objective, json.dumps(plan.focus, ensure_ascii=False),
                    json.dumps(plan.queries, ensure_ascii=False), plan.rationale, utc_now(),
                ),
            )
            for query in plan.queries:
                conn.execute(
                    """INSERT OR IGNORE INTO queries(run_id, round_no, query, status, created_at)
                       VALUES (?, ?, ?, 'pending', ?)""",
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
                "SELECT * FROM queries WHERE run_id=? ORDER BY round_no, id", (run_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def completed_queries(self, run_id: str) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT query FROM queries WHERE run_id=? AND status='completed' ORDER BY id", (run_id,)
            ).fetchall()
        return [row["query"] for row in rows]

    def complete_query(self, run_id: str, round_no: int, query: str, error: str | None = None) -> None:
        status = "failed" if error else "completed"
        with self.connect() as conn:
            conn.execute(
                """UPDATE queries SET status=?, completed_at=?, error=?
                   WHERE run_id=? AND round_no=? AND query=?""",
                (status, utc_now(), error, run_id, round_no, query),
            )

    def add_search_result(
        self, run_id: str, query: str, rank: int, result: SearchResult
    ) -> int:
        from urllib.parse import urlsplit

        canonical = canonicalize_url(result.url)
        domain = (urlsplit(canonical).hostname or "").lower()
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO sources(canonical_url, url, title, domain, first_seen_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(canonical_url) DO UPDATE SET
                     title=CASE WHEN excluded.title!='' THEN excluded.title ELSE sources.title END,
                     url=excluded.url""",
                (canonical, result.url, result.title, domain, now),
            )
            source_id = conn.execute(
                "SELECT id FROM sources WHERE canonical_url=?", (canonical,)
            ).fetchone()["id"]
            conn.execute(
                """INSERT INTO run_sources
                   (run_id, source_id, search_query, rank, snippet, engine, category,
                    published_at, raw_json, discovered_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id, source_id, search_query, engine, category) DO UPDATE SET
                     rank=MIN(run_sources.rank, excluded.rank),
                     snippet=CASE WHEN length(excluded.snippet)>length(run_sources.snippet)
                                  THEN excluded.snippet ELSE run_sources.snippet END,
                     published_at=COALESCE(excluded.published_at, run_sources.published_at),
                     raw_json=excluded.raw_json""",
                (
                    run_id, source_id, query, rank, result.snippet, result.engine, result.category,
                    result.published_at, json.dumps(result.raw, ensure_ascii=False), now,
                ),
            )
        return int(source_id)

    def latest_snapshot(self, source_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE source_id=? ORDER BY fetched_at DESC LIMIT 1",
                (source_id,),
            ).fetchone()
        return dict(row) if row else None

    def save_snapshot(
        self,
        source_id: int,
        final_url: str,
        status_code: int,
        content_type: str,
        content_hash: str,
        raw: bytes,
        text: str,
        extracted_title: str,
    ) -> None:
        base = self.data_dir / "sources" / content_hash[:2] / content_hash
        base.parent.mkdir(parents=True, exist_ok=True)
        raw_path = base.with_suffix(".html.gz")
        text_path = base.with_suffix(".txt")
        if not raw_path.exists():
            with gzip.open(raw_path, "wb", compresslevel=6) as fh:
                fh.write(raw)
        if not text_path.exists():
            text_path.write_text(text, encoding="utf-8")
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO snapshots
                   (source_id, fetched_at, final_url, status_code, content_type, content_hash,
                    raw_path, text_path, extracted_title)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    source_id, utc_now(), final_url, status_code, content_type, content_hash,
                    str(raw_path), str(text_path), extracted_title,
                ),
            )

    def sources_for_run(self, run_id: str, limit: int = 500) -> list[SourceView]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT s.id, s.url, s.canonical_url, s.title, s.domain,
                          rs.snippet, rs.search_query, rs.rank, rs.engine, rs.category,
                          rs.published_at, rs.discovered_at,
                          sn.text_path
                   FROM run_sources rs
                   JOIN sources s ON s.id=rs.source_id
                   LEFT JOIN snapshots sn ON sn.id=(
                       SELECT id FROM snapshots x WHERE x.source_id=s.id ORDER BY fetched_at DESC LIMIT 1
                   )
                   WHERE rs.run_id=?
                   GROUP BY s.id
                   ORDER BY MIN(rs.rank), s.id
                   LIMIT ?""",
                (run_id, limit),
            ).fetchall()
        out: list[SourceView] = []
        for row in rows:
            excerpt = ""
            if row["text_path"]:
                try:
                    excerpt = Path(row["text_path"]).read_text(encoding="utf-8")[:4000]
                except OSError:
                    pass
            out.append(SourceView(
                id=row["id"], url=row["url"], canonical_url=row["canonical_url"],
                title=row["title"], domain=row["domain"], snippet=row["snippet"],
                search_query=row["search_query"], rank=row["rank"], engine=row["engine"],
                category=row["category"], published_at=row["published_at"],
                discovered_at=row["discovered_at"], fetched=bool(row["text_path"]),
                text_excerpt=excerpt,
            ))
        return out

    def event(self, run_id: str | None, kind: str, message: str, data: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO events(run_id, ts, kind, message, data_json) VALUES (?, ?, ?, ?, ?)",
                (run_id, utc_now(), kind, message, json.dumps(data or {}, ensure_ascii=False)),
            )

    def discoveries_for_run(self, run_id: str, limit: int = 5000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT rs.*, s.url, s.canonical_url, s.title, s.domain
                   FROM run_sources rs JOIN sources s ON s.id=rs.source_id
                   WHERE rs.run_id=? ORDER BY rs.discovered_at, rs.rank LIMIT ?""",
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

    def source_discoveries(self, run_id: str, source_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT search_query, rank, engine, category, published_at, discovered_at
                   FROM run_sources WHERE run_id=? AND source_id=?
                   ORDER BY discovered_at, rank""",
                (run_id, source_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def events_for_run(self, run_id: str, limit: int = 300) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE run_id=? ORDER BY id DESC LIMIT ?", (run_id, limit)
            ).fetchall()
        return [dict(row) for row in reversed(rows)]
