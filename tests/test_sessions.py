from pathlib import Path

from traceweave.storage import Storage


def test_session_persists_state(tmp_path: Path):
    storage = Storage(tmp_path / "db.sqlite", tmp_path / "data")
    storage.init()
    sid = storage.create_session("work")
    storage.update_session(sid, angle="infrastructure", mode="deep", shell_enabled=True)
    row = storage.get_session(sid)
    assert row and row["angle"] == "infrastructure" and row["mode"] == "deep" and row["shell_enabled"] == 1
