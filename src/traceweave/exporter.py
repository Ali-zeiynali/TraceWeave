from __future__ import annotations

import json
from pathlib import Path

from traceweave.storage import Storage


class Exporter:
    def __init__(self, storage: Storage, export_dir: Path):
        self.storage = storage
        self.export_dir = export_dir
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def markdown(self, run_id: str) -> Path:
        run = self.storage.get_run(run_id)
        if not run:
            raise KeyError(f"Unknown run: {run_id}")
        sources = self.storage.sources_for_run(run_id, limit=2000)
        events = self.storage.events_for_run(run_id, limit=1000)
        lines = [
            f"# TraceWeave research: {run['topic']}",
            "",
            f"- Run: `{run_id}`",
            f"- Status: `{run['status']}`",
            f"- Mode: `{run['mode']}`",
            f"- Angle: {run['angle'] or '—'}",
            f"- Created: {run['created_at']}",
            f"- Completed rounds: {run['current_round']}/{run['max_rounds']}",
            "",
            "## Research brief",
            "",
            run.get("final_summary") or "No LLM synthesis is stored for this run. The source inventory below is still complete.",
            "",
            "## Sources",
            "",
        ]
        for source in sources:
            date = f" — {source.published_at}" if source.published_at else ""
            discoveries = self.storage.source_discoveries(run_id, source.id)
            lines.extend([
                f"### [S{source.id}] {source.title or source.domain or source.url}",
                "",
                f"- URL: {source.url}",
                f"- Domain: `{source.domain}`{date}",
                f"- Snapshot fetched: {'yes' if source.fetched else 'no'}",
                "- Discovery paths:",
            ])
            for discovery in discoveries:
                lines.append(
                    f"  - `{discovery['search_query']}` — rank {discovery['rank']}, "
                    f"{discovery['engine']}, {discovery['category']}"
                )
            lines.extend([
                "",
                source.snippet.strip() or "_No search snippet stored._",
                "",
            ])
        lines.extend(["## Research trail", ""])
        for event in events:
            lines.append(f"- `{event['ts']}` **{event['kind']}** — {event['message']}")
        path = self.export_dir / f"{run_id}.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def json(self, run_id: str) -> Path:
        run = self.storage.get_run(run_id)
        if not run:
            raise KeyError(f"Unknown run: {run_id}")
        payload = {
            "run": run,
            "sources": [s.model_dump() for s in self.storage.sources_for_run(run_id, limit=5000)],
            "discoveries": self.storage.discoveries_for_run(run_id, limit=10000),
            "events": self.storage.events_for_run(run_id, limit=5000),
        }
        path = self.export_dir / f"{run_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
    def mermaid(self, run_id: str) -> Path:
        run = self.storage.get_run(run_id)
        if not run:
            raise KeyError(f"Unknown run: {run_id}")
        queries = self.storage.queries_for_run(run_id)
        discoveries = self.storage.discoveries_for_run(run_id, limit=10000)

        def esc(value: str) -> str:
            return value.replace("\\", "\\\\").replace('"', "'").replace("\n", " ")[:90]

        lines = [
            "flowchart TD",
            f'  RUN["Run {run_id}: {esc(run["topic"])}"]',
        ]
        rounds = sorted({int(q["round_no"]) for q in queries})
        for round_no in rounds:
            lines.append(f'  R{round_no}["Round {round_no}"]')
            lines.append(f"  RUN --> R{round_no}")
        query_nodes: dict[str, str] = {}
        for item in queries:
            qid = f"Q{item['id']}"
            query_nodes[item["query"]] = qid
            lines.append(f'  {qid}["{esc(item["query"])}"]')
            lines.append(f"  R{item['round_no']} --> {qid}")
        source_ids: set[int] = set()
        for item in discoveries:
            sid = int(item["source_id"])
            snode = f"S{sid}"
            if sid not in source_ids:
                source_ids.add(sid)
                label = esc(item.get("title") or item.get("domain") or item.get("url") or f"S{sid}")
                lines.append(f'  {snode}["S{sid}: {label}"]')
            qnode = query_nodes.get(item["search_query"])
            if qnode:
                lines.append(f"  {qnode} --> {snode}")
        path = self.export_dir / f"{run_id}.mmd"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

