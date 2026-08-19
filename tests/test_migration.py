from pathlib import Path
import sqlite3

from traceweave.storage import Storage


def test_v01_database_migrates_in_place(tmp_path: Path):
    db = tmp_path / "db.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript('''
        CREATE TABLE runs (
          id TEXT PRIMARY KEY, topic TEXT NOT NULL, angle TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL,
          language TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          current_round INTEGER NOT NULL DEFAULT 0, max_rounds INTEGER NOT NULL,
          max_results_per_query INTEGER NOT NULL, fetch_top_per_query INTEGER NOT NULL,
          last_error TEXT, final_summary TEXT
        );
        CREATE TABLE plans (
          id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, round_no INTEGER NOT NULL,
          objective TEXT NOT NULL, focus_json TEXT NOT NULL, queries_json TEXT NOT NULL,
          rationale TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, UNIQUE(run_id,round_no)
        );
        CREATE TABLE sources (id INTEGER PRIMARY KEY AUTOINCREMENT, canonical_url TEXT NOT NULL UNIQUE, url TEXT NOT NULL,
          title TEXT NOT NULL DEFAULT '', domain TEXT NOT NULL DEFAULT '', first_seen_at TEXT NOT NULL);
        CREATE TABLE snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, source_id INTEGER NOT NULL, fetched_at TEXT NOT NULL,
          final_url TEXT NOT NULL,status_code INTEGER NOT NULL,content_type TEXT NOT NULL DEFAULT '',content_hash TEXT NOT NULL,
          raw_path TEXT,text_path TEXT,extracted_title TEXT NOT NULL DEFAULT '',UNIQUE(source_id,content_hash));
        ''')
    storage = Storage(db, tmp_path / "data")
    storage.init()
    with storage.connect() as conn:
        run_cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
        plan_cols = {r[1] for r in conn.execute("PRAGMA table_info(plans)")}
        snap_cols = {r[1] for r in conn.execute("PRAGMA table_info(snapshots)")}
    assert {"max_depth", "max_frontier_pages"} <= run_cols
    assert {"gaps_json", "source_classes_json"} <= plan_cols
    assert "simhash" in snap_cols
