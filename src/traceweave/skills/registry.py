from __future__ import annotations

import tomllib
from importlib.resources import files
from pathlib import Path
from typing import Any


class SkillRegistry:
    """Progressive skill loader: only task-relevant small instructions enter model context."""

    def __init__(self, project_dir: Path = Path(".traceweave/skills")) -> None:
        root = files("traceweave.skills")
        raw = tomllib.loads(root.joinpath("catalog.toml").read_text(encoding="utf-8"))
        self._builtin = [({**item, "_origin": "builtin"}, root) for item in raw.get("skills", [])]
        self._project_dir = Path(project_dir)

    @staticmethod
    def _skill_metadata(path: Path) -> dict[str, Any]:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return {}
        metadata: dict[str, Any] = {}
        if text.startswith("---\n"):
            header, marker, _ = text[4:].partition("\n---")
            if marker:
                for raw in header.splitlines():
                    key, sep, value = raw.partition(":")
                    if sep:
                        metadata[key.strip().replace("-", "_")] = value.strip().strip("'\"")
        tasks = metadata.get("traceweave_tasks", "")
        metadata["tasks"] = [item.strip() for item in str(tasks).split(",") if item.strip()]
        metadata["name"] = metadata.get("name") or path.parent.name
        metadata["file"] = path.name
        metadata["_origin"] = "agent-skill"
        return metadata

    def _agent_skill_entries(self) -> list[tuple[dict[str, Any], Path]]:
        entries: list[tuple[dict[str, Any], Path]] = []
        seen: set[Path] = set()
        current = Path.cwd().resolve()
        roots = [current]
        while current.parent != current and not (current / ".git").exists():
            current = current.parent
            roots.append(current)
        for root in roots:
            for base in (
                root / ".agents" / "skills",
                root / ".opencode" / "skills",
                root / ".claude" / "skills",
            ):
                if not base.is_dir():
                    continue
                for path in sorted(base.glob("*/SKILL.md")):
                    resolved = path.resolve()
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    metadata = self._skill_metadata(path)
                    if metadata:
                        entries.append((metadata, path.parent))
        return entries

    def _entries(self) -> list[tuple[dict[str, Any], Any]]:
        entries = list(self._builtin)
        catalog = self._project_dir / "catalog.toml"
        if catalog.is_file():
            try:
                raw = tomllib.loads(catalog.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = {}
            entries.extend(
                ({**item, "_origin": "project"}, self._project_dir) for item in raw.get("skills", [])
            )
        entries.extend(self._agent_skill_entries())
        return entries

    def for_task(self, task: str) -> str:
        chunks: list[str] = []
        selected = sorted(
            (
                (item, root)
                for item, root in self._entries()
                if item.get("enabled", True)
                and (task in item.get("tasks", []) or "*" in item.get("tasks", []))
            ),
            key=lambda row: int(row[0].get("priority", 100)),
        )
        for item, root in selected:
            try:
                content = root.joinpath(item["file"]).read_text(encoding="utf-8").strip()
            except (OSError, KeyError):
                continue
            chunks.append(content[: int(item.get("max_chars", 6000))])
        return "\n\n".join(chunks)

    def status_rows(self) -> list[dict[str, object]]:
        return [
            {
                "name": str(item.get("name") or item.get("file") or "unnamed"),
                "version": str(item.get("version") or "1"),
                "tasks": list(item.get("tasks") or []),
                "enabled": bool(item.get("enabled", True)),
                "origin": str(item.get("_origin") or ("project" if isinstance(root, Path) else "builtin")),
            }
            for item, root in self._entries()
        ]
