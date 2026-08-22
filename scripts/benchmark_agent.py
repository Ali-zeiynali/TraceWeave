"""End-to-end TraceWeave benchmark runner.

Runs the public bounded research CLI in child processes, exports each completed run, and stores a
deterministic evidence/coverage scorecard. It never reads or writes API key values.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

DEFAULT_PROMPTS = (
    "Give me a brief, cited report on Cloudflare Workers AI changes announced in 2026.",
    "یک گزارش کوتاه و مستند درباره تغییرات مهم Cloudflare Workers AI در سال 2026 بده.",
    "Briefly investigate the public evidence for SQLite improvements released during 2026, including counter-evidence.",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompts", nargs="*", help="Research prompt(s) used as benchmark topics")
    parser.add_argument("--mode", choices=("quick", "standard", "deep", "overnight"), default="quick")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--depth", type=int, default=0)
    parser.add_argument("--frontier-budget", type=int, default=0)
    parser.add_argument("--max-model-calls", type=int, default=16)
    parser.add_argument("--deadline-minutes", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument(
        "--prefer-model",
        action="append",
        default=[],
        help="Repeat exact deployment keys to run a model-route A/B matrix; omit for auto routing.",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = root / ".traceweave" / "benchmarks" / stamp
    out.mkdir(parents=True, exist_ok=True)
    prompts = tuple(args.prompts) or DEFAULT_PROMPTS
    manifest: dict[str, object] = {
        "created_at": datetime.now(UTC).isoformat(),
        "runner": "traceweave research (public bounded CLI)",
        "zero_cost_only": True,
        "mode": args.mode,
        "cases": [],
    }
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", "TRACEWEAVE_ZERO_COST_ONLY": "true"})
    variants = args.prefer_model or [""]
    matrix = [(prompt, route) for prompt in prompts for route in variants]
    for index, (prompt, preferred_route) in enumerate(matrix, 1):
        print(
            f"[{index}/{len(matrix)}] starting prompt ({len(prompt)} chars), "
            f"route={preferred_route or 'auto'}",
            flush=True,
        )
        started = monotonic()
        case_dir = out / f"case-{index:02d}"
        case_dir.mkdir()
        command = [
            sys.executable,
            "-m",
            "traceweave",
            "research",
            prompt,
            "--mode",
            args.mode,
            "--rounds",
            str(args.rounds),
            "--depth",
            str(args.depth),
            "--frontier-budget",
            str(args.frontier_budget),
            "--max-model-calls",
            str(args.max_model_calls),
            "--deadline-minutes",
            str(args.deadline_minutes),
        ]
        if preferred_route:
            command.extend(("--prefer-model", preferred_route))
        result = subprocess.run(
            command,
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.timeout_seconds,
            check=False,
        )
        duration_seconds = round(monotonic() - started, 3)
        (case_dir / "stdout.txt").write_text(result.stdout, encoding="utf-8")
        (case_dir / "stderr.txt").write_text(result.stderr, encoding="utf-8")
        matches = re.findall(r"\b[0-9a-f]{12}\b", result.stdout)
        run_id = matches[-1] if matches else ""
        score: dict[str, object] = {
            "prompt": prompt,
            "preferred_route": preferred_route or "auto",
            "exit_code": result.returncode,
            "run_id": run_id,
            "completed": bool(run_id and result.returncode == 0),
            "duration_seconds": duration_seconds,
        }
        export_path = root / ".traceweave" / "exports" / f"{run_id}.json"
        if run_id:
            subprocess.run(
                [sys.executable, "-m", "traceweave", "export", run_id, "--format", "json"],
                cwd=root,
                env=env,
                capture_output=True,
                timeout=180,
                check=False,
            )
        if export_path.is_file():
            payload = json.loads(export_path.read_text(encoding="utf-8"))
            copied = case_dir / "run.json"
            copied.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            sources = payload.get("sources", [])
            claims = payload.get("claims", [])
            citations = payload.get("citations", [])
            queries = payload.get("queries", [])
            observations = payload.get("observations", [])
            edges = payload.get("research_edges", [])
            provider_usage = payload.get("provider_usage", [])
            assessments = payload.get("claim_assessments", [])
            identity_hypotheses = payload.get("identity_hypotheses", [])
            domains = {item.get("domain") for item in sources if item.get("domain")}
            categories = {item.get("category") for item in sources if item.get("category")}
            verified = sum(bool(item.get("verified_span")) for item in claims)
            summary = str((payload.get("run") or {}).get("final_summary") or "")
            report_citations = len(set(re.findall(r"\[S(\d+)\]", summary)))
            summary_low = summary.casefold()
            synthesis_success = bool(summary) and not any(
                marker in summary_low
                for marker in ("provider failed", "synthesis was unavailable", "deterministic fallback")
            )
            official_sources = sum(
                any(
                    marker in str(item.get("domain") or "").casefold()
                    for marker in ("cloudflare.com", "github.com", "ietf.org", "gov", "edu")
                )
                or float(item.get("authority") or 0) >= 80
                for item in sources
            )
            quality_score = min(
                100,
                min(24, len(domains) * 3)
                + min(15, len(categories) * 3)
                + min(30, verified * 2)
                + min(10, report_citations * 2)
                + min(11, official_sources)
                + (5 if len(summary) >= 500 else 0)
                + (5 if synthesis_success else 0),
            )
            score.update(
                {
                    "sources": len(sources),
                    "unique_domains": len(domains),
                    "source_categories": len(categories),
                    "claims": len(claims),
                    "verified_claims": verified,
                    "claim_assessments": len(assessments),
                    "corroborated_claims": sum(item.get("verdict") == "corroborated" for item in assessments),
                    "contested_claims": sum(item.get("verdict") == "contested" for item in assessments),
                    "identity_hypotheses": len(identity_hypotheses),
                    "citation_leads": len(citations),
                    "report_citations": report_citations,
                    "queries": len(queries),
                    "latin_queries": sum(
                        any("a" <= c.casefold() <= "z" for c in str(q.get("query") or "")) for q in queries
                    ),
                    "non_latin_queries": sum(
                        any(ord(c) > 127 for c in str(q.get("query") or "")) for q in queries
                    ),
                    "observations": len(observations),
                    "research_edges": len(edges),
                    "provider_requests": sum(int(row.get("requests") or 0) for row in provider_usage),
                    "provider_failures": sum(int(row.get("failures") or 0) for row in provider_usage),
                    "official_sources": official_sources,
                    "summary_chars": len(summary),
                    "synthesis_success": synthesis_success,
                    "quality_score": quality_score,
                }
            )
        print(
            f"[{index}/{len(matrix)}] completed in {duration_seconds:.1f}s: {run_id or 'no run id'}",
            flush=True,
        )
        (case_dir / "score.json").write_text(
            json.dumps(score, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        manifest["cases"].append(score)  # type: ignore[union-attr]
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    return 0 if all(case.get("completed") for case in manifest["cases"]) else 1  # type: ignore[union-attr]


if __name__ == "__main__":
    raise SystemExit(main())
