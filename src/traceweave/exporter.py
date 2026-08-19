from __future__ import annotations

import json
from pathlib import Path

from traceweave.storage import Storage


class Exporter:
    def __init__(self, storage: Storage, export_dir: Path):
        self.storage = storage
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def markdown(self, run_id: str) -> Path:
        run = self._run(run_id)
        sources = self.storage.sources_for_run(run_id, 5000)
        claims = self.storage.claims_for_run(run_id, 5000)
        events = self.storage.events_for_run(run_id, 5000)
        lines = [
            f"# TraceWeave research — {run['topic']}", "",
            f"- Run: `{run_id}`", f"- Status: `{run['status']}`", f"- Mode: `{run['mode']}`",
            f"- Angle: {run['angle'] or '_none_'}", f"- Rounds: {run['current_round']}/{run['max_rounds']}",
            f"- Frontier depth / budget: {run.get('max_depth', 0)} / {run.get('max_frontier_pages', 0)}", "",
            "## Final synthesis", "", run.get("final_summary") or "_Not synthesized yet._", "",
            "## Grounded claims", "",
        ]
        for c in claims:
            state = "verified span" if c.get("verified_span") else "unverified span"
            lines.extend([
                f"### C{c['id']} — [S{c['source_id']}]", "",
                c["claim_text"], "",
                f"- Confidence: {float(c['confidence']):.2f}", f"- Evidence: {state}",
                f"> {str(c.get('quote') or '').replace(chr(10), ' ')[:1200]}", "",
            ])
        if not claims:
            lines.extend(["_No model-grounded claims were extracted._", ""])
        lines.extend(["## Sources", ""])
        for s in sources:
            discoveries = self.storage.source_discoveries(run_id, s.id)
            lines.extend([
                f"### [S{s.id}] {s.title or s.domain or s.url}", "", f"- URL: {s.url}", f"- Domain: `{s.domain}`",
                f"- Fetched snapshot: {'yes' if s.fetched else 'no'}",
                f"- Scores: relevance={_n(s.relevance)}, importance={_n(s.importance)}, novelty={_n(s.novelty)}, authority={_n(s.authority)}",
                f"- Duplicate of: {'S'+str(s.duplicate_of) if s.duplicate_of else '—'}",
                f"- Source family: `{s.family_key or 'unassigned'}`", "- Discovery paths:",
            ])
            for d in discoveries:
                lines.append(f"  - `{d['search_query']}` — rank {d['rank']}, {d['engine']}, {d['category']}")
            lines.extend(["", s.snippet.strip() or "_No search snippet stored._", ""])
        lines.extend(["## Research trail", ""])
        for e in events:
            lines.append(f"- `{e['ts']}` **{e['kind']}** — {e['message']}")
        path = self.export_dir / f"{run_id}.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def evidence(self, run_id: str) -> Path:
        run = self._run(run_id)
        claims = self.storage.claims_for_run(run_id, 5000)
        lines = [f"# Evidence matrix — {run['topic']}", "", "| Claim | Source | Confidence | Verified quote |", "|---|---:|---:|---|" ]
        for c in claims:
            quote = str(c.get("quote") or "").replace("|", "\\|").replace("\n", " ")[:500]
            claim = str(c["claim_text"]).replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {claim} | S{c['source_id']} | {float(c['confidence']):.2f} | {quote} |")
        path = self.export_dir / f"{run_id}.evidence.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def json(self, run_id: str) -> Path:
        run = self._run(run_id)
        payload = {
            "run": run,
            "plans": [self.storage.get_plan(run_id, i).model_dump() for i in range(1, int(run["max_rounds"]) + 1) if self.storage.get_plan(run_id, i)],
            "sources": [s.model_dump() for s in self.storage.sources_for_run(run_id, 5000)],
            "discoveries": self.storage.discoveries_for_run(run_id, 10000),
            "claims": self.storage.claims_for_run(run_id, 5000),
            "frontier": self.storage.frontier_for_run(run_id, 10000),
            "events": self.storage.events_for_run(run_id, 10000),
        }
        path = self.export_dir / f"{run_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return path

    def mermaid(self, run_id: str) -> Path:
        run = self._run(run_id)
        queries = self.storage.queries_for_run(run_id)
        discoveries = self.storage.discoveries_for_run(run_id, 10000)
        frontier = self.storage.frontier_for_run(run_id, 10000)

        def esc(value: str) -> str:
            return value.replace("\\", "\\\\").replace('"', "'").replace("\n", " ")[:90]

        lines = ["flowchart TD", f'  RUN["Run {run_id}: {esc(run["topic"])}"]']
        rounds = sorted({int(q["round_no"]) for q in queries})
        for r in rounds:
            lines.extend([f'  R{r}["Round {r}"]', f"  RUN --> R{r}"])
        query_nodes: dict[tuple[int, str], str] = {}
        for item in queries:
            qid = f"Q{item['id']}"; query_nodes[(int(item["round_no"]), item["query"])] = qid
            lines.extend([f'  {qid}["{esc(item["query"])}"]', f"  R{item['round_no']} --> {qid}"])
        source_ids: set[int] = set()
        for item in discoveries:
            sid = int(item["source_id"]); snode = f"S{sid}"
            if sid not in source_ids:
                source_ids.add(sid); label = esc(item.get("title") or item.get("domain") or item.get("url") or snode)
                lines.append(f'  {snode}["S{sid}: {label}"]')
            # Query text can appear in multiple rounds; link it to all matching query nodes.
            for (round_no, query), qnode in query_nodes.items():
                if query == item["search_query"]:
                    lines.append(f"  {qnode} --> {snode}")
        for item in frontier:
            parent = item.get("parent_source_id")
            if not parent:
                continue
            canonical = item["canonical_url"]
            child = next((d for d in discoveries if d.get("canonical_url") == canonical), None)
            if child:
                relation = esc(str(item.get("relation") or "link"))
                lines.append(f"  S{parent} -->|{relation}| S{child['source_id']}")
        path = self.export_dir / f"{run_id}.mmd"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _run(self, run_id: str) -> dict:
        run = self.storage.get_run(run_id)
        if not run:
            raise KeyError(f"Unknown run: {run_id}")
        return run


def _n(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f}"
