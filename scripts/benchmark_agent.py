"""End-to-end TraceWeave benchmark runner.

Runs the public prompt-first CLI in child processes, exports each completed run, and stores a
deterministic evidence/coverage scorecard. It never reads or writes API key values.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_PROMPTS = (
    "Give me a brief, cited report on Cloudflare Workers AI changes announced in 2026.",
    "یک گزارش کوتاه و مستند درباره تغییرات مهم Cloudflare Workers AI در سال 2026 بده.",
    "Briefly investigate the public evidence for SQLite improvements released during 2026, including counter-evidence.",
)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = root / ".traceweave" / "benchmarks" / stamp
    out.mkdir(parents=True, exist_ok=True)
    prompts = tuple(sys.argv[1:]) or DEFAULT_PROMPTS
    manifest: dict[str, object] = {
        "created_at": datetime.now(UTC).isoformat(),
        "runner": "traceweave ask (public CLI)",
        "zero_cost_only": True,
        "cases": [],
    }
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", "TRACEWEAVE_ZERO_COST_ONLY": "true"})
    for index, prompt in enumerate(prompts, 1):
        case_dir = out / f"case-{index:02d}"
        case_dir.mkdir()
        result = subprocess.run(
            [sys.executable, "-m", "traceweave", "ask", prompt],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60 * 20,
            check=False,
        )
        (case_dir / "stdout.txt").write_text(result.stdout, encoding="utf-8")
        (case_dir / "stderr.txt").write_text(result.stderr, encoding="utf-8")
        matches = re.findall(r"\b[0-9a-f]{12}\b", result.stdout)
        run_id = matches[-1] if matches else ""
        score: dict[str, object] = {
            "prompt": prompt,
            "exit_code": result.returncode,
            "run_id": run_id,
            "completed": bool(run_id and result.returncode == 0),
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
            domains = {item.get("domain") for item in sources if item.get("domain")}
            categories = {item.get("category") for item in sources if item.get("category")}
            verified = sum(bool(item.get("verified_span")) for item in claims)
            summary = str((payload.get("run") or {}).get("final_summary") or "")
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
                for item in sources
            )
            quality_score = min(
                100,
                min(24, len(domains) * 3)
                + min(15, len(categories) * 3)
                + min(30, verified * 2)
                + min(10, len(citations) * 2)
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
                    "citations": len(citations),
                    "official_sources": official_sources,
                    "summary_chars": len(summary),
                    "synthesis_success": synthesis_success,
                    "quality_score": quality_score,
                }
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
