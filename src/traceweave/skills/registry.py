from __future__ import annotations

import tomllib
from importlib.resources import files


class SkillRegistry:
    """Progressive skill loader: only task-relevant small instructions enter model context."""

    def __init__(self) -> None:
        root = files("traceweave.skills")
        raw = tomllib.loads(root.joinpath("catalog.toml").read_text(encoding="utf-8"))
        self._skills = list(raw.get("skills", []))
        self._root = root

    def for_task(self, task: str) -> str:
        chunks: list[str] = []
        for item in self._skills:
            if task in item.get("tasks", []):
                chunks.append(self._root.joinpath(item["file"]).read_text(encoding="utf-8").strip())
        return "\n\n".join(chunks)
