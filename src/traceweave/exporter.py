from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from xml.sax.saxutils import escape

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
        archives = self.storage.archive_captures_for_run(run_id, 5000)
        citations = self.storage.citations_for_run(run_id, 5000)
        entities = self.storage.entities_for_run(run_id, 5000)
        relationships = self.storage.relationships_for_run(run_id, 5000)
        timeline = self.storage.timeline_for_run(run_id, 5000)
        artifacts = self.storage.artifacts_for_run(run_id, 5000)
        observations = self.storage.observations_for_run(run_id, 5000)
        lines = [
            f"# TraceWeave research — {run['topic']}",
            "",
            f"- Run: `{run_id}`",
            f"- Status: `{run['status']}`",
            f"- Mode: `{run['mode']}`",
            f"- Angle: {run['angle'] or '_none_'}",
            f"- Rounds: {run['current_round']}/{run['max_rounds']}",
            f"- Frontier depth / budget: {run.get('max_depth', 0)} / {run.get('max_frontier_pages', 0)}",
            "",
            "## Final synthesis",
            "",
            run.get("final_summary") or "_Not synthesized yet._",
            "",
            "## Grounded claims",
            "",
        ]
        for c in claims:
            state = "verified span" if c.get("verified_span") else "unverified span"
            lines.extend(
                [
                    f"### C{c['id']} — [S{c['source_id']}]",
                    "",
                    c["claim_text"],
                    "",
                    f"- Confidence: {float(c['confidence']):.2f}",
                    f"- Evidence: {state}",
                    f"> {str(c.get('quote') or '').replace(chr(10), ' ')[:1200]}",
                    "",
                ]
            )
        if not claims:
            lines.extend(["_No model-grounded claims were extracted._", ""])
        lines.extend(["## Sources", ""])
        for s in sources:
            discoveries = self.storage.source_discoveries(run_id, s.id)
            lines.extend(
                [
                    f"### [S{s.id}] {s.title or s.domain or s.url}",
                    "",
                    f"- URL: {s.url}",
                    f"- Domain: `{s.domain}`",
                    f"- Fetched snapshot: {'yes' if s.fetched else 'no'}",
                    f"- Scores: relevance={_n(s.relevance)}, importance={_n(s.importance)}, novelty={_n(s.novelty)}, authority={_n(s.authority)}",
                    f"- Duplicate of: {'S' + str(s.duplicate_of) if s.duplicate_of else '—'}",
                    f"- Source family: `{s.family_key or 'unassigned'}`",
                    "- Discovery paths:",
                ]
            )
            for d in discoveries:
                lines.append(f"  - `{d['search_query']}` — rank {d['rank']}, {d['engine']}, {d['category']}")
            lines.extend(["", s.snippet.strip() or "_No search snippet stored._", ""])
        lines.extend(
            [
                "## Historical / specialist state",
                "",
                f"- Archive captures: {len(archives)}",
                f"- Citation leads: {len(citations)}",
                f"- Entities: {len(entities)}",
                f"- Relationships: {len(relationships)}",
                "",
            ]
        )
        if artifacts or observations:
            lines.extend(
                [
                    "## Media / observations",
                    "",
                    f"- Artifacts: {len(artifacts)}",
                    f"- Observations: {len(observations)}",
                    "",
                ]
            )
            for item in observations[:250]:
                lines.append(
                    f"- O{item['id']} `{item['kind']}` importance={float(item['importance']):.0f} "
                    f"rarity={float(item['rarity']):.0f} — {item['value_text'][:300]}"
                )
            lines.append("")
        if timeline:
            lines.extend(["## Timeline", ""])
            for item in timeline[:250]:
                lines.append(f"- `{item['event_time']}` {item['label']} [S{item.get('source_id') or 0}]")
            lines.append("")
        lines.extend(["## Research trail", ""])
        for e in events:
            lines.append(f"- `{e['ts']}` **{e['kind']}** — {e['message']}")
        path = self.export_dir / f"{run_id}.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def evidence(self, run_id: str) -> Path:
        run = self._run(run_id)
        claims = self.storage.claims_for_run(run_id, 5000)
        assessments = {
            int(item["claim_id"]): item for item in self.storage.claim_assessments_for_run(run_id, 5000)
        }
        lines = [
            f"# Evidence matrix — {run['topic']}",
            "",
            "| Claim | Source | Confidence | Verdict | Verified quote |",
            "|---|---:|---:|---|---|",
        ]
        for c in claims:
            quote = str(c.get("quote") or "").replace("|", "\\|").replace("\n", " ")[:500]
            claim = str(c["claim_text"]).replace("|", "\\|").replace("\n", " ")
            verdict = assessments.get(int(c["id"]), {}).get("verdict", "unassessed")
            lines.append(
                f"| {claim} | S{c['source_id']} | {float(c['confidence']):.2f} | {verdict} | {quote} |"
            )
        path = self.export_dir / f"{run_id}.evidence.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def json(self, run_id: str) -> Path:
        run = self._run(run_id)
        payload = {
            "run": run,
            "plans": [
                self.storage.get_plan(run_id, i).model_dump()
                for i in range(1, int(run["max_rounds"]) + 1)
                if self.storage.get_plan(run_id, i)
            ],
            "sources": [s.model_dump() for s in self.storage.sources_for_run(run_id, 5000)],
            "queries": self.storage.queries_for_run(run_id),
            "provider_usage": self.storage.provider_usage(run_id=run_id, limit=1000),
            "discoveries": self.storage.discoveries_for_run(run_id, 10000),
            "claims": self.storage.claims_for_run(run_id, 5000),
            "claim_assessments": self.storage.claim_assessments_for_run(run_id, 5000),
            "frontier": self.storage.frontier_for_run(run_id, 10000),
            "archives": self.storage.archive_captures_for_run(run_id, 10000),
            "citations": self.storage.citations_for_run(run_id, 10000),
            "entities": self.storage.entities_for_run(run_id, 10000),
            "relationships": self.storage.relationships_for_run(run_id, 10000),
            "timeline": self.storage.timeline_for_run(run_id, 10000),
            "artifacts": self.storage.artifacts_for_run(run_id, 10000),
            "media_leads": self.storage.media_leads_for_run(run_id, 10000),
            "observations": self.storage.observations_for_run(run_id, 10000),
            "identity_hypotheses": self.storage.identity_hypotheses_for_run(run_id, 5000),
            "artifact_matches": self.storage.artifact_matches_for_run(run_id, 5000),
            "tasks": self.storage.tasks_for_run(run_id, 10000),
            "research_edges": self.storage.research_edges_for_run(run_id, 20000),
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
            qid = f"Q{item['id']}"
            query_nodes[(int(item["round_no"]), item["query"])] = qid
            lines.extend([f'  {qid}["{esc(item["query"])}"]', f"  R{item['round_no']} --> {qid}"])
        source_ids: set[int] = set()
        for item in discoveries:
            sid = int(item["source_id"])
            snode = f"S{sid}"
            if sid not in source_ids:
                source_ids.add(sid)
                label = esc(item.get("title") or item.get("domain") or item.get("url") or snode)
                lines.append(f'  {snode}["S{sid}: {label}"]')
            # Query text can appear in multiple rounds; link it to all matching query nodes.
            for (_round_no, query), qnode in query_nodes.items():
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
        entities = self.storage.entities_for_run(run_id, 250)
        relationships = self.storage.relationships_for_run(run_id, 500)
        for ent in entities:
            lines.append(f'  E{ent["id"]}(("{esc(ent["canonical_name"])}"))')
        for rel in relationships:
            if rel.get("target_entity_id"):
                lines.append(
                    f"  E{rel['source_entity_id']} -->|{esc(rel['predicate'])}| E{rel['target_entity_id']}"
                )
            if rel.get("source_id"):
                lines.append(f"  S{rel['source_id']} -.evidence.-> E{rel['source_entity_id']}")
        for artifact in self.storage.artifacts_for_run(run_id, 250):
            aid = _mermaid_id("A", str(artifact["id"]))
            lines.append(f'  {aid}["Artifact: {esc(artifact["media_type"])}"]')
            if artifact.get("source_id"):
                lines.append(f"  S{artifact['source_id']} -->|media| {aid}")
        for observation in self.storage.observations_for_run(run_id, 500):
            oid = f"O{observation['id']}"
            lines.append(f'  {oid}["{esc(observation["value_text"])}"]')
            if observation.get("artifact_id"):
                lines.append(f"  {_mermaid_id('A', str(observation['artifact_id']))} -->|observed| {oid}")
        path = self.export_dir / f"{run_id}.mmd"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def graphml(self, run_id: str) -> Path:
        run = self._run(run_id)
        edges = self.storage.research_edges_for_run(run_id, 100_000)
        nodes: dict[str, tuple[str, str]] = {f"run:{run_id}": ("run", str(run["topic"]))}
        for edge in edges:
            source = f"{edge['from_type']}:{edge['from_id']}"
            target = f"{edge['to_type']}:{edge['to_id']}"
            nodes.setdefault(source, (str(edge["from_type"]), str(edge["from_id"])))
            nodes.setdefault(target, (str(edge["to_type"]), str(edge["to_id"])))
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
            '  <key id="type" for="node" attr.name="type" attr.type="string"/>',
            '  <key id="label" for="node" attr.name="label" attr.type="string"/>',
            '  <key id="relation" for="edge" attr.name="relation" attr.type="string"/>',
            f'  <graph id="{escape(run_id)}" edgedefault="directed">',
        ]
        ids: dict[str, str] = {}
        for index, (key, (node_type, label)) in enumerate(nodes.items(), 1):
            node_id = f"n{index}"
            ids[key] = node_id
            lines.extend(
                [
                    f'    <node id="{node_id}">',
                    f'      <data key="type">{escape(node_type)}</data>',
                    f'      <data key="label">{escape(label)}</data>',
                    "    </node>",
                ]
            )
        for index, edge in enumerate(edges, 1):
            source = ids[f"{edge['from_type']}:{edge['from_id']}"]
            target = ids[f"{edge['to_type']}:{edge['to_id']}"]
            lines.extend(
                [
                    f'    <edge id="e{index}" source="{source}" target="{target}">',
                    f'      <data key="relation">{escape(str(edge["relation"]))}</data>',
                    "    </edge>",
                ]
            )
        lines.extend(["  </graph>", "</graphml>"])
        path = self.export_dir / f"{run_id}.graphml"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def case(self, run_id: str) -> Path:
        """Refresh a self-contained, human-readable case workspace for an active run."""
        run = self._run(run_id)
        case_dir = self.export_dir / run_id
        case_dir.mkdir(parents=True, exist_ok=True)
        scoped = Exporter(self.storage, case_dir)
        markdown = scoped.markdown(run_id)
        findings = scoped.json(run_id)
        mermaid = scoped.mermaid(run_id)
        graphml = scoped.graphml(run_id)
        evidence = scoped.evidence(run_id)
        shutil.copy2(markdown, case_dir / "report.md")
        shutil.copy2(findings, case_dir / "findings.json")

        observations = self.storage.observations_for_run(run_id, 10_000)
        important = {
            str(item["artifact_id"])
            for item in observations
            if item.get("artifact_id") and float(item.get("importance") or 0) >= 60
        }
        media_dir = case_dir / "media"
        media_dir.mkdir(exist_ok=True)
        media_index: list[dict[str, object]] = []
        for artifact in self.storage.artifacts_for_run(run_id, 10_000):
            if important and str(artifact["id"]) not in important:
                continue
            source = Path(str(artifact.get("path") or ""))
            if not source.is_file():
                continue
            suffix = source.suffix or ".bin"
            target = media_dir / f"{artifact['id']}{suffix}"
            if not target.exists():
                try:
                    os.link(source, target)
                except OSError:
                    shutil.copy2(source, target)
            media_index.append(
                {
                    "artifact_id": artifact["id"],
                    "source_id": artifact.get("source_id"),
                    "media_type": artifact.get("media_type"),
                    "sha256": artifact.get("sha256"),
                    "path": str(target.relative_to(case_dir)),
                }
            )

        manifest = {
            "run_id": run_id,
            "topic": run["topic"],
            "status": run["status"],
            "updated_at": run["updated_at"],
            "report": "report.md",
            "findings": "findings.json",
            "evidence": evidence.name,
            "mermaid": mermaid.name,
            "graphml": graphml.name,
            "important_media": media_index,
        }
        (case_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        return case_dir

    def _run(self, run_id: str) -> dict:
        run = self.storage.get_run(run_id)
        if not run:
            raise KeyError(f"Unknown run: {run_id}")
        return run


def _n(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f}"


def _mermaid_id(prefix: str, value: str) -> str:
    return prefix + "".join(character if character.isalnum() else "_" for character in value)
