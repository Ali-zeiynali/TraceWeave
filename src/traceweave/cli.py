from __future__ import annotations

import asyncio
import json
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from traceweave import __version__
from traceweave.exporter import Exporter
from traceweave.models import ProgressEvent, ResearchSpec
from traceweave.runtime import build_runtime

app = typer.Typer(
    name="traceweave", help="Iterative evidence-first research with durable provenance and model routing.",
    no_args_is_help=False, invoke_without_command=True, add_completion=True,
)
console = Console()


@app.callback()
def main(ctx: typer.Context) -> None:
    """Open the TUI when no subcommand is supplied."""
    if ctx.invoked_subcommand is None:
        from traceweave.tui.app import TraceWeaveApp
        TraceWeaveApp().run()


@app.command()
def tui() -> None:
    """Launch the full-screen terminal UI."""
    from traceweave.tui.app import TraceWeaveApp
    TraceWeaveApp().run()


@app.command()
def research(
    topic: Annotated[str, typer.Argument(help="Research topic or question")],
    angle: Annotated[str, typer.Option("--angle", "-a", help="Research angle / prioritization lens")] = "",
    mode: Annotated[str, typer.Option("--mode", "-m", help="quick, standard, or deep")] = "standard",
    rounds: Annotated[int | None, typer.Option("--rounds", "-r", help="Plan/search rounds")]=None,
    language: Annotated[str, typer.Option("--language", "-l", help="Search language, or all")]="all",
    depth: Annotated[int | None, typer.Option("--depth", help="Best-first recursive depth, 0..5")]=None,
    frontier_budget: Annotated[int | None, typer.Option("--frontier-budget", help="Max recursive pages, 0..500")]=None,
) -> None:
    """Run iterative research without opening the TUI."""
    if mode not in {"quick", "standard", "deep"}:
        raise typer.BadParameter("mode must be quick, standard, or deep")

    async def progress(event: ProgressEvent) -> None:
        color = {
            "run.failed": "red", "search.failed": "red", "source.fetch_failed": "yellow",
            "source.discovered": "cyan", "source.triaged": "blue", "claim.extracted": "green",
            "frontier.visit": "yellow", "plan.ready": "magenta", "run.completed": "green",
        }.get(event.kind, "dim")
        console.print(f"[{color}]{event.kind}[/{color}] {event.message}")

    async def run() -> str:
        runtime = build_runtime(callback=progress)
        spec = ResearchSpec(
            topic=topic, angle=angle, mode=mode, max_rounds=rounds, language=language,
            max_depth=depth, max_frontier_pages=frontier_budget,
        )
        return await runtime.engine.start(spec)

    try:
        run_id = asyncio.run(run())
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted. Durable state is saved; use traceweave resume RUN_ID.[/yellow]")
        raise typer.Exit(130)
    console.print(f"\n[bold green]Completed:[/bold green] {run_id}")
    console.print(f"Export: [bold]traceweave export {run_id}[/bold]")


@app.command("resume")
def resume_run(run_id: Annotated[str, typer.Argument(help="Run ID to resume")]) -> None:
    """Resume a paused, failed, or interrupted run including frontier leases."""
    async def progress(event: ProgressEvent) -> None:
        console.print(f"[dim]{event.kind}[/dim] {event.message}")
    async def run() -> None:
        await build_runtime(callback=progress).engine.resume(run_id)
    try:
        asyncio.run(run())
    except KeyError as exc:
        console.print(f"[red]{exc}[/red]"); raise typer.Exit(2)


@app.command("runs")
def runs(limit: int = 30) -> None:
    """List recent research runs."""
    runtime = build_runtime(); table = Table(title="TraceWeave runs")
    for col in ("ID", "Status", "Round", "Mode", "Depth", "Topic", "Created"):
        table.add_column(col)
    for row in runtime.storage.list_runs(limit):
        table.add_row(row["id"], row["status"], f"{row['current_round']}/{row['max_rounds']}", row["mode"],
                      str(row.get("max_depth", 0)), row["topic"][:70], row["created_at"][:19])
    console.print(table)


@app.command("show")
def show(run_id: str) -> None:
    """Show run metadata, source scores, and claim counts."""
    runtime = build_runtime(); run = runtime.storage.get_run(run_id)
    if not run:
        console.print(f"[red]Unknown run: {run_id}[/red]"); raise typer.Exit(2)
    console.print_json(json.dumps(run, ensure_ascii=False))
    table = Table(title=f"Sources for {run_id}")
    for col in ("ID", "Type", "Imp", "Rel", "Nov", "Title", "Domain", "Fetched"):
        table.add_column(col)
    for s in runtime.storage.sources_for_run(run_id, 100):
        table.add_row(f"S{s.id}", s.category, _score(s.importance), _score(s.relevance), _score(s.novelty),
                      s.title[:60], s.domain, "yes" if s.fetched else "no")
    console.print(table)
    console.print(f"Grounded claims: {len(runtime.storage.claims_for_run(run_id, 5000))}")
    console.print(f"Frontier: {runtime.storage.frontier_stats(run_id)}")


@app.command("claims")
def claims(run_id: str, limit: int = 100) -> None:
    """List grounded claims and source ids."""
    runtime = build_runtime(); table = Table(title=f"Claims — {run_id}")
    table.add_column("ID"); table.add_column("Source"); table.add_column("Conf"); table.add_column("Claim")
    for c in runtime.storage.claims_for_run(run_id, limit):
        table.add_row(f"C{c['id']}", f"S{c['source_id']}", f"{float(c['confidence']):.2f}", c["claim_text"][:120])
    console.print(table)


@app.command("providers")
def providers(task: str = "general", reload: bool = typer.Option(False, "--reload", help="Reload providers.toml before display")) -> None:
    """Show provider/token/model routes and persistent health."""
    runtime = build_runtime();
    if reload and runtime.router:
        runtime.router.reload()
    table = Table(title=f"Provider routes (task={task})")
    for col in ("Provider", "Credential", "Model", "Driver", "Healthy", "Cooldown", "OK", "Fail", "Latency", "Tasks"):
        table.add_column(col)
    if not runtime.router:
        console.print("[yellow]No usable routes. Configure providers.toml and token environment variables.[/yellow]"); return
    for row in runtime.router.status_rows(task):
        table.add_row(str(row["provider"]), str(row["credential"]), str(row["model"]), str(row["driver"]),
                      "yes" if row["healthy"] else "no", f"{row['cooldown_seconds']}s", str(row["successes"]),
                      str(row["failures"]), f"{row['latency']}s", str(row["tasks"]))
    console.print(table)


@app.command("router-log")
def router_log(limit: int = 50) -> None:
    """Show recent model routing attempts without exposing API tokens."""
    runtime = build_runtime(); table = Table(title="Router attempts")
    for col in ("When", "Task", "Route", "OK", "Failure", "Status", "Latency"):
        table.add_column(col)
    for row in runtime.storage.router_attempts(limit):
        table.add_row(row["created_at"][:19], row["task"], row["deployment_key"], "yes" if row["ok"] else "no",
                      row["failure_kind"] or "", str(row["status_code"] or ""), f"{float(row['latency_seconds'] or 0):.2f}s")
    console.print(table)


@app.command("sessions")
def sessions() -> None:
    """List persistent TUI sessions."""
    runtime = build_runtime(); table = Table(title="TraceWeave sessions")
    for c in ("ID", "Name", "Mode", "Angle", "Run", "Updated"):
        table.add_column(c)
    for row in runtime.storage.list_sessions(100):
        table.add_row(row["id"], row["name"], row["mode"], row["angle"][:35], row["active_run_id"] or "", row["updated_at"][:19])
    console.print(table)


@app.command("export")
def export_run(
    run_id: str,
    format: Annotated[str, typer.Option("--format", "-f", help="md, json, mermaid, or evidence")] = "md",
) -> None:
    """Export source provenance, graph, and evidence."""
    runtime = build_runtime(); exporter = Exporter(runtime.storage, runtime.settings.data_dir / "exports")
    try:
        funcs = {"md": exporter.markdown, "json": exporter.json, "mermaid": exporter.mermaid,
                 "mmd": exporter.mermaid, "evidence": exporter.evidence}
        if format not in funcs:
            raise typer.BadParameter("format must be md, json, mermaid, or evidence")
        path = funcs[format](run_id)
    except KeyError as exc:
        console.print(f"[red]{exc}[/red]"); raise typer.Exit(2)
    console.print(f"[green]Exported:[/green] {path}")


@app.command()
def doctor() -> None:
    """Check storage, search config, provider mesh, and optional features."""
    runtime = build_runtime(); settings = runtime.settings
    table = Table(title="TraceWeave doctor")
    table.add_column("Check"); table.add_column("Value"); table.add_column("Status")
    checks = [
        ("Version", __version__, "ok"), ("Data directory", str(settings.data_dir.resolve()), "ok"),
        ("Database", str(settings.db_path.resolve()), "ok" if settings.db_path.exists() else "created on first use"),
        ("Search backend", settings.search_backend, "ok"), ("SearXNG", settings.searxng_url, "configured"),
        ("Provider config", str(settings.provider_config), "present" if settings.provider_config.exists() else "missing"),
        ("Usable LLM routes", str(len(runtime.router.deployments) if runtime.router else 0), "optional" if not runtime.router else "ok"),
        ("Browser fallback", str(settings.browser_fallback), "optional"),
        ("Respect robots", str(settings.respect_robots), "ok"),
    ]
    for name, value, status in checks:
        table.add_row(name, value, status)
    console.print(table)
    if not runtime.router:
        console.print("[yellow]No usable model routes: deterministic planning/triage and source-only synthesis remain available.[/yellow]")


@app.command()
def version() -> None:
    """Print version."""
    console.print(__version__)


def _score(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f}"
