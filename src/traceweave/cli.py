from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from traceweave import __version__
from traceweave.exporter import Exporter
from traceweave.models import ProgressEvent, ResearchSpec
from traceweave.runtime import build_runtime

app = typer.Typer(
    name="traceweave",
    help="Iterative research with complete source provenance.",
    no_args_is_help=False,
    invoke_without_command=True,
    add_completion=True,
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
    rounds: Annotated[int | None, typer.Option("--rounds", "-r", help="Override number of plan/search rounds")] = None,
    language: Annotated[str, typer.Option("--language", "-l", help="Search language, or all")] = "all",
) -> None:
    """Run research from the normal CLI without opening the TUI."""
    if mode not in {"quick", "standard", "deep"}:
        raise typer.BadParameter("mode must be quick, standard, or deep")

    async def progress(event: ProgressEvent) -> None:
        color = {
            "run.failed": "red",
            "search.failed": "red",
            "source.fetch_failed": "yellow",
            "source.discovered": "cyan",
            "plan.ready": "magenta",
            "run.completed": "green",
        }.get(event.kind, "dim")
        console.print(f"[{color}]{event.kind}[/{color}] {event.message}")

    async def run() -> str:
        runtime = build_runtime(callback=progress)
        spec = ResearchSpec(topic=topic, angle=angle, mode=mode, max_rounds=rounds, language=language)
        return await runtime.engine.start(spec)

    try:
        run_id = asyncio.run(run())
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted. The run state has been saved and can be resumed.[/yellow]")
        raise typer.Exit(130)
    console.print(f"\n[bold green]Completed:[/bold green] {run_id}")
    console.print(f"Use: [bold]traceweave export {run_id}[/bold]")


@app.command("resume")
def resume_run(run_id: Annotated[str, typer.Argument(help="Run ID to resume")]) -> None:
    """Resume a paused, failed, or interrupted run."""
    async def progress(event: ProgressEvent) -> None:
        console.print(f"[dim]{event.kind}[/dim] {event.message}")

    async def run() -> None:
        runtime = build_runtime(callback=progress)
        await runtime.engine.resume(run_id)

    try:
        asyncio.run(run())
    except KeyError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2)


@app.command("runs")
def runs(limit: int = 30) -> None:
    """List recent research runs."""
    runtime = build_runtime()
    table = Table(title="TraceWeave runs")
    for col in ("ID", "Status", "Round", "Mode", "Topic", "Created"):
        table.add_column(col)
    for row in runtime.storage.list_runs(limit):
        table.add_row(
            row["id"], row["status"], f"{row['current_round']}/{row['max_rounds']}",
            row["mode"], row["topic"][:70], row["created_at"][:19],
        )
    console.print(table)


@app.command("show")
def show(run_id: str) -> None:
    """Show run metadata and discovered sources."""
    runtime = build_runtime()
    run = runtime.storage.get_run(run_id)
    if not run:
        console.print(f"[red]Unknown run: {run_id}[/red]")
        raise typer.Exit(2)
    console.print_json(json.dumps(run, ensure_ascii=False))
    table = Table(title=f"Sources for {run_id}")
    table.add_column("ID")
    table.add_column("Type")
    table.add_column("Title")
    table.add_column("Domain")
    table.add_column("Fetched")
    for source in runtime.storage.sources_for_run(run_id, 100):
        table.add_row(f"S{source.id}", source.category, source.title[:70], source.domain, "yes" if source.fetched else "no")
    console.print(table)


@app.command("export")
def export_run(
    run_id: str,
    format: Annotated[str, typer.Option("--format", "-f", help="md, json, or mermaid")] = "md",
) -> None:
    """Export a run with its source inventory and research trail."""
    runtime = build_runtime()
    exporter = Exporter(runtime.storage, runtime.settings.data_dir / "exports")
    try:
        if format == "md":
            path = exporter.markdown(run_id)
        elif format == "json":
            path = exporter.json(run_id)
        elif format in {"mermaid", "mmd"}:
            path = exporter.mermaid(run_id)
        else:
            raise typer.BadParameter("format must be md, json, or mermaid")
    except KeyError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2)
    console.print(f"[green]Exported:[/green] {path}")


@app.command()
def doctor() -> None:
    """Check local configuration and storage readiness."""
    runtime = build_runtime()
    settings = runtime.settings
    table = Table(title="TraceWeave doctor")
    table.add_column("Check")
    table.add_column("Value")
    table.add_column("Status")
    checks = [
        ("Version", __version__, "ok"),
        ("Data directory", str(settings.data_dir.resolve()), "ok"),
        ("Database", str(settings.db_path.resolve()), "ok" if settings.db_path.exists() else "created on first use"),
        ("Search backend", settings.search_backend, "ok"),
        ("SearXNG", settings.searxng_url, "configured"),
        ("LLM", settings.model or "not configured", "optional" if not settings.llm_configured else "ok"),
    ]
    for name, value, status in checks:
        table.add_row(name, value, status)
    console.print(table)
    if not settings.llm_configured:
        console.print("[yellow]No LLM configured: planning will use deterministic fallback and synthesis will be source-only.[/yellow]")


@app.command()
def version() -> None:
    """Print version."""
    console.print(__version__)
