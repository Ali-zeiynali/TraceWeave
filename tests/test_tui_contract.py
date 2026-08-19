from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def test_tui_css_does_not_use_unsupported_auto_margin() -> None:
    app_path = Path(__file__).parents[1] / "src" / "traceweave" / "tui" / "app.py"
    text = app_path.read_text(encoding="utf-8")
    assert "margin: auto" not in text
    assert "CenterMiddle" in text
    assert '#workspace { display: none;' in text
    assert "Footer" not in text


@pytest.mark.asyncio
async def test_tui_landing_mounts_and_workspace_starts_hidden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if importlib.util.find_spec("textual") is None:
        pytest.skip("Textual is not installed in this build environment")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRACEWEAVE_DATA_DIR", str(tmp_path / "state"))
    # Keep startup offline and deterministic for the UI contract test.
    for prefix in ("AGENTROUTER", "SEEKROUTER", "ZENMUX", "OPENROUTER", "MISTRAL", "GEMINI", "GROQ"):
        for suffix in ("_API_KEY", "_API_KEY_1", "_API_KEY_2", "_API_KEY_3"):
            monkeypatch.delenv(prefix + suffix, raising=False)

    from textual.widgets import Input
    from traceweave.tui.app import TraceWeaveApp

    app = TraceWeaveApp()
    async with app.run_test(size=(120, 40)):
        launch = app.query_one("#launch-input", Input)
        workspace = app.query_one("#workspace")
        landing = app.query_one("#landing")
        assert launch.has_focus
        assert bool(landing.display)
        assert not bool(workspace.display)
