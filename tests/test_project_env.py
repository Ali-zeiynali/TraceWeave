from pathlib import Path

from traceweave.config import load_project_env


def test_project_env_loads_provider_keys_without_overwriting_parent_env(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GROQ_API_KEY='from-file'\nEXISTING=from-file\n", encoding="utf-8")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("EXISTING", "from-parent")
    load_project_env(env_file)
    assert __import__("os").environ["GROQ_API_KEY"] == "from-file"
    assert __import__("os").environ["EXISTING"] == "from-parent"
