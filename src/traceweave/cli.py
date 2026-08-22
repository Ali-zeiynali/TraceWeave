from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from traceweave import __version__
from traceweave.exporter import Exporter
from traceweave.mcp import MCPError, StreamableHTTPMCPClient, load_mcp_servers
from traceweave.models import ProgressEvent, ResearchSpec
from traceweave.runtime import build_runtime
from traceweave.skills import SkillRegistry
from traceweave.sources.social import TelegramPublicSource
from traceweave.tooling import tool_status_rows

app = typer.Typer(
    name="traceweave",
    help="Iterative evidence-first research with durable provenance and model routing.",
    no_args_is_help=False,
    invoke_without_command=True,
    add_completion=True,
)
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        with contextlib.suppress(OSError, ValueError):
            _stream.reconfigure(encoding="utf-8", errors="replace")
console = Console(legacy_windows=False)


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
    mode: Annotated[str, typer.Option("--mode", "-m", help="quick, standard, deep, or overnight")] = "deep",
    rounds: Annotated[int | None, typer.Option("--rounds", "-r", help="Plan/search rounds")] = None,
    language: Annotated[str, typer.Option("--language", "-l", help="Search language, or all")] = "all",
    depth: Annotated[int | None, typer.Option("--depth", help="Best-first recursive depth, 0..5")] = None,
    frontier_budget: Annotated[
        int | None, typer.Option("--frontier-budget", help="Max recursive pages, 0..500")
    ] = None,
    deadline_minutes: Annotated[
        int | None, typer.Option("--deadline-minutes", help="Persistent wall-clock deadline")
    ] = None,
    max_model_calls: Annotated[
        int | None, typer.Option("--max-model-calls", help="Hard per-run model-attempt budget")
    ] = None,
    allow_remote_vision: Annotated[
        bool, typer.Option("--allow-remote-vision", help="Opt in to configured remote vision")
    ] = False,
    max_vision_calls: Annotated[
        int, typer.Option("--max-vision-calls", help="Hard per-run remote vision-attempt budget")
    ] = 0,
    prefer_model: Annotated[
        str,
        typer.Option(
            "--prefer-model",
            help="Exact deployment key from `traceweave providers --json`; healthy fallback remains enabled",
        ),
    ] = "",
) -> None:
    """Run iterative research without opening the TUI."""
    if mode not in {"quick", "standard", "deep", "overnight"}:
        raise typer.BadParameter("mode must be quick, standard, deep, or overnight")

    async def progress(event: ProgressEvent) -> None:
        color = {
            "run.failed": "red",
            "search.failed": "red",
            "source.fetch_failed": "yellow",
            "source.discovered": "cyan",
            "source.triaged": "blue",
            "claim.extracted": "green",
            "frontier.visit": "yellow",
            "plan.ready": "magenta",
            "run.completed": "green",
        }.get(event.kind, "dim")
        console.print(f"[{color}]{event.kind}[/{color}] {event.message}")

    runtime = build_runtime(callback=progress)
    if prefer_model and (runtime.router is None or not runtime.router.prefer(prefer_model)):
        raise typer.BadParameter("unknown deployment key; use `traceweave providers --task planning --json`")

    async def run() -> str:
        spec = ResearchSpec(
            topic=topic,
            angle=angle,
            mode=mode,
            max_rounds=rounds,
            language=language,
            max_depth=depth,
            max_frontier_pages=frontier_budget,
            deadline_minutes=deadline_minutes,
            max_model_calls=max_model_calls,
            allow_remote_vision=allow_remote_vision,
            max_vision_calls=max_vision_calls,
        )
        return await runtime.engine.start(spec)

    try:
        run_id = asyncio.run(run())
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted. Durable state is saved; use traceweave resume RUN_ID.[/yellow]")
        raise typer.Exit(130) from None
    console.print(f"\n[bold green]Completed:[/bold green] {run_id}")
    console.print(f"Export: [bold]traceweave export {run_id}[/bold]")


@app.command()
def ask(prompt: Annotated[str, typer.Argument(help="Natural-language research request")]) -> None:
    """Run the prompt-first agent without research flags."""

    async def progress(event: ProgressEvent) -> None:
        console.print(f"[dim]{event.kind}[/dim] {event.message}")

    async def run() -> str:
        return await build_runtime(callback=progress).engine.start_prompt(prompt)

    try:
        run_id = asyncio.run(run())
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted. Durable state is saved and can be resumed.[/yellow]")
        raise typer.Exit(130) from None
    console.print(f"\n[bold green]Completed:[/bold green] {run_id}")


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
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from None


@app.command("runs")
def runs(limit: int = 30) -> None:
    """List recent research runs."""
    runtime = build_runtime()
    table = Table(title="TraceWeave runs")
    for col in ("ID", "Status", "Round", "Mode", "Depth", "Topic", "Created"):
        table.add_column(col)
    for row in runtime.storage.list_runs(limit):
        table.add_row(
            row["id"],
            row["status"],
            f"{row['current_round']}/{row['max_rounds']}",
            row["mode"],
            str(row.get("max_depth", 0)),
            row["topic"][:70],
            row["created_at"][:19],
        )
    console.print(table)


@app.command("show")
def show(run_id: str) -> None:
    """Show run metadata, source scores, and claim counts."""
    runtime = build_runtime()
    run = runtime.storage.get_run(run_id)
    if not run:
        console.print(f"[red]Unknown run: {run_id}[/red]")
        raise typer.Exit(2) from None
    console.print_json(json.dumps(run, ensure_ascii=False))
    table = Table(title=f"Sources for {run_id}")
    for col in ("ID", "Type", "Imp", "Rel", "Nov", "Title", "Domain", "Fetched"):
        table.add_column(col)
    for s in runtime.storage.sources_for_run(run_id, 100):
        table.add_row(
            f"S{s.id}",
            s.category,
            _score(s.importance),
            _score(s.relevance),
            _score(s.novelty),
            s.title[:60],
            s.domain,
            "yes" if s.fetched else "no",
        )
    console.print(table)
    console.print(f"Grounded claims: {len(runtime.storage.claims_for_run(run_id, 5000))}")
    console.print(f"Frontier: {runtime.storage.frontier_stats(run_id)}")


@app.command("claims")
def claims(run_id: str, limit: int = 100) -> None:
    """List grounded claims and source ids."""
    runtime = build_runtime()
    table = Table(title=f"Claims — {run_id}")
    table.add_column("ID")
    table.add_column("Source")
    table.add_column("Conf")
    table.add_column("Claim")
    for c in runtime.storage.claims_for_run(run_id, limit):
        table.add_row(
            f"C{c['id']}", f"S{c['source_id']}", f"{float(c['confidence']):.2f}", c["claim_text"][:120]
        )
    console.print(table)


@app.command("providers")
def providers(
    task: str = "general",
    reload: bool = typer.Option(
        False, "--reload", help="Reload provider presets/providers.toml before display"
    ),
    sync: bool = typer.Option(
        False, "--sync", help="Refresh credential-scoped /models catalogs before display"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit exact deployment keys and health as machine-readable JSON"
    ),
) -> None:
    """Show provider/token/model routes and persistent health."""
    runtime = build_runtime()
    sync_result: dict[str, str] = {}
    if runtime.router and sync:
        sync_result = asyncio.run(runtime.router.ensure_catalogs(force=True))
        runtime.router.reload()
        if not json_output:
            console.print(f"[dim]Catalog sync: {sync_result or 'nothing to refresh'}[/dim]")
    if reload and runtime.router:
        runtime.router.reload()
    rows = runtime.router.status_rows(task) if runtime.router else []
    if json_output:
        console.print_json(data={"task": task, "catalog_sync": sync_result, "routes": rows})
        return
    table = Table(title=f"Provider routes (task={task})")
    for col in (
        "Provider",
        "Credential",
        "Model",
        "Driver",
        "Healthy",
        "Cooldown",
        "OK",
        "Fail",
        "Latency",
        "Tasks",
    ):
        table.add_column(col)
    if not runtime.router:
        console.print(
            "[yellow]No usable routes. Configure providers.toml and token environment variables.[/yellow]"
        )
        return
    for row in rows:
        table.add_row(
            str(row["provider"]),
            str(row["credential"]),
            str(row["model"]),
            str(row["driver"]),
            "yes" if row["healthy"] else "no",
            f"{row['cooldown_seconds']}s",
            str(row["successes"]),
            str(row["failures"]),
            f"{row['latency']}s",
            str(row["tasks"]),
        )
    console.print(table)


@app.command("toolbox")
def toolbox(category: str = "") -> None:
    """Show passive OSINT integrations, stability, policy, and missing credentials/binaries."""
    table = Table(title="TraceWeave passive toolbox")
    for col in ("Tool", "Category", "Stability", "Status", "Access", "Notes"):
        table.add_column(col)
    for row in tool_status_rows():
        if category and row["category"] != category:
            continue
        table.add_row(
            str(row["id"]),
            str(row["category"]),
            str(row["stability"]),
            str(row["status"]),
            str(row["access"]),
            str(row["notes"]),
        )
    console.print(table)


@app.command("mcp")
def mcp(
    server: Annotated[str, typer.Option("--server", "-s", help="Configured MCP server name")] = "",
) -> None:
    """List configured Streamable HTTP MCP servers and their exposed tools."""
    servers = [item for item in load_mcp_servers() if item.enabled]
    if server:
        servers = [item for item in servers if item.name == server]
    if not servers:
        console.print("[yellow]No matching enabled servers in .traceweave/mcp.toml.[/yellow]")
        return

    async def inspect() -> list[tuple[object, list[dict] | Exception]]:
        rows = []
        for item in servers:
            try:
                tools = await StreamableHTTPMCPClient(item).list_tools()
                rows.append((item, tools))
            except (MCPError, httpx.HTTPError) as exc:
                rows.append((item, exc))
        return rows

    import httpx

    table = Table(title="TraceWeave MCP tool discovery")
    for column in ("Server", "Mode", "Tool", "Allowed", "Description"):
        table.add_column(column)
    for item, result in asyncio.run(inspect()):
        if isinstance(result, Exception):
            table.add_row(item.name, "error", "—", "no", str(result)[:100])
            continue
        for tool in result:
            name = str(tool.get("name") or "")
            table.add_row(
                item.name,
                "read-only" if item.read_only else "mixed",
                name,
                "yes" if name in item.allowed_tools else "no",
                str(tool.get("description") or "")[:100],
            )
    console.print(table)


@app.command("skills")
def skills() -> None:
    """Show built-in and hot-loaded project skills and their task scopes."""
    table = Table(title="TraceWeave skills")
    for col in ("Skill", "Version", "Origin", "Enabled", "Tasks"):
        table.add_column(col)
    for row in SkillRegistry().status_rows():
        table.add_row(
            str(row["name"]),
            str(row["version"]),
            str(row["origin"]),
            "yes" if row["enabled"] else "no",
            ", ".join(str(task) for task in row["tasks"]),
        )
    console.print(table)


@app.command("telegram-login")
def telegram_login() -> None:
    """Interactively authorize the official Telegram user session once."""
    # Runtime construction loads .env and initializes the normal durable state first.
    build_runtime()
    source = TelegramPublicSource.from_env()
    if source is None:
        console.print("[red]Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first.[/red]")
        raise typer.Exit(2) from None
    try:
        identity = asyncio.run(source.authorize())
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    console.print(f"[green]Telegram session authorized:[/green] {identity}")


@app.command("archives")
def archives(run_id: str, limit: int = 100) -> None:
    """List Wayback/Common Crawl captures stored for a run."""
    runtime = build_runtime()
    table = Table(title=f"Archives — {run_id}")
    for c in ("ID", "Source", "Engine", "Captured", "URL"):
        table.add_column(c)
    for row in runtime.storage.archive_captures_for_run(run_id, limit):
        table.add_row(
            f"A{row['id']}",
            f"S{row['source_id']}",
            row["engine"],
            row["captured_at"],
            row["capture_url"][:100],
        )
    console.print(table)


@app.command("entities")
def entities(run_id: str, limit: int = 100) -> None:
    """List grounded graph entities for a run."""
    runtime = build_runtime()
    table = Table(title=f"Entities — {run_id}")
    for c in ("ID", "Type", "Confidence", "Name"):
        table.add_column(c)
    for row in runtime.storage.entities_for_run(run_id, limit):
        table.add_row(
            f"E{row['id']}", row["entity_type"], f"{float(row['confidence']):.2f}", row["canonical_name"]
        )
    console.print(table)


@app.command("verification")
def verification(run_id: str, limit: int = 200) -> None:
    """List claim corroboration and contradiction assessments."""
    runtime = build_runtime()
    table = Table(title=f"Verification — {run_id}")
    for column in ("Claim", "Verdict", "Confidence", "Support", "Conflict", "Rationale"):
        table.add_column(column)
    for row in runtime.storage.claim_assessments_for_run(run_id, limit):
        table.add_row(
            f"C{row['claim_id']}",
            row["verdict"],
            f"{float(row['confidence']):.2f}",
            ",".join(f"C{value}" for value in row["supporting_claim_ids"]),
            ",".join(f"C{value}" for value in row["conflicting_claim_ids"]),
            row["rationale"][:100],
        )
    console.print(table)


@app.command("identity")
def identity(run_id: str, limit: int = 100) -> None:
    """List reviewable identity hypotheses and near-duplicate public media."""
    runtime = build_runtime()
    table = Table(title=f"Identity hypotheses — {run_id}")
    for column in ("Entities", "Verdict", "Confidence", "Names", "Evidence"):
        table.add_column(column)
    for row in runtime.storage.identity_hypotheses_for_run(run_id, limit):
        table.add_row(
            f"E{row['left_entity_id']}↔E{row['right_entity_id']}",
            row["verdict"],
            f"{float(row['confidence']):.2f}",
            f"{row['left_name']} / {row['right_name']}",
            ",".join(f"C{value}" for value in row["evidence_claim_ids"]),
        )
    console.print(table)


@app.command("timeline")
def timeline(run_id: str, limit: int = 100) -> None:
    """List claim-grounded timeline events."""
    runtime = build_runtime()
    table = Table(title=f"Timeline — {run_id}")
    for c in ("When", "Source", "Confidence", "Event"):
        table.add_column(c)
    for row in runtime.storage.timeline_for_run(run_id, limit):
        table.add_row(
            row["event_time"],
            f"S{row.get('source_id') or 0}",
            f"{float(row['confidence']):.2f}",
            row["label"][:120],
        )
    console.print(table)


@app.command("router-log")
def router_log(limit: int = 50) -> None:
    """Show recent model routing attempts without exposing API tokens."""
    runtime = build_runtime()
    table = Table(title="Router attempts")
    for col in ("When", "Task", "Route", "OK", "Failure", "Status", "Latency"):
        table.add_column(col)
    for row in runtime.storage.router_attempts(limit):
        table.add_row(
            row["created_at"][:19],
            row["task"],
            row["deployment_key"],
            "yes" if row["ok"] else "no",
            row["failure_kind"] or "",
            str(row["status_code"] or ""),
            f"{float(row['latency_seconds'] or 0):.2f}s",
        )
    console.print(table)


@app.command("sessions")
def sessions() -> None:
    """List persistent TUI sessions."""
    runtime = build_runtime()
    table = Table(title="TraceWeave sessions")
    for c in ("ID", "Name", "Mode", "Angle", "Run", "Updated"):
        table.add_column(c)
    for row in runtime.storage.list_sessions(100):
        table.add_row(
            row["id"],
            row["name"],
            row["mode"],
            row["angle"][:35],
            row["active_run_id"] or "",
            row["updated_at"][:19],
        )
    console.print(table)


@app.command("export")
def export_run(
    run_id: str,
    format: Annotated[
        str, typer.Option("--format", "-f", help="md, json, mermaid, graphml, or evidence")
    ] = "md",
) -> None:
    """Export source provenance, graph, and evidence."""
    runtime = build_runtime()
    exporter = Exporter(runtime.storage, runtime.settings.data_dir / "exports")
    try:
        funcs = {
            "md": exporter.markdown,
            "json": exporter.json,
            "mermaid": exporter.mermaid,
            "mmd": exporter.mermaid,
            "graphml": exporter.graphml,
            "evidence": exporter.evidence,
        }
        if format not in funcs:
            raise typer.BadParameter("format must be md, json, mermaid, graphml, or evidence")
        path = funcs[format](run_id)
    except KeyError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    console.print(f"[green]Exported:[/green] {path}")


@app.command()
def doctor() -> None:
    """Check storage, search config, provider mesh, and optional features."""
    runtime = build_runtime()
    settings = runtime.settings
    table = Table(title="TraceWeave doctor")
    table.add_column("Check")
    table.add_column("Value")
    table.add_column("Status")
    checks = [
        ("Version", __version__, "ok"),
        ("Data directory", str(settings.data_dir.resolve()), "ok"),
        (
            "Database",
            str(settings.db_path.resolve()),
            "ok" if settings.db_path.exists() else "created on first use",
        ),
        ("Search backend", settings.search_backend, "ok"),
        ("SearXNG", settings.searxng_url, "configured"),
        (
            "Provider config",
            str(settings.provider_config),
            "present" if settings.provider_config.exists() else "missing",
        ),
        (
            "Usable LLM routes",
            str(len(runtime.router.deployments) if runtime.router else 0),
            "optional" if not runtime.router else "ok",
        ),
        (
            "Stage 4 archives",
            str(settings.archives_enabled),
            "ok" if settings.archives_enabled else "disabled",
        ),
        (
            "Academic sources",
            str(settings.academic_enabled),
            "ok" if settings.academic_enabled else "disabled",
        ),
        (
            "GitHub public sources",
            str(settings.github_enabled),
            "ok" if settings.github_enabled else "disabled",
        ),
        (
            "Entity graph",
            str(settings.entity_graph_enabled),
            "ok" if settings.entity_graph_enabled else "disabled",
        ),
        (
            "Public registries",
            str(settings.registry_sources_enabled),
            "ok" if settings.registry_sources_enabled else "disabled",
        ),
        (
            "Public social",
            str(settings.public_social_enabled),
            "ok" if settings.public_social_enabled else "disabled",
        ),
        ("Media collection", str(settings.media_enabled), "ok" if settings.media_enabled else "disabled"),
        ("Remote vision", str(settings.remote_vision_enabled), "opt-in"),
        ("Browser fallback", str(settings.browser_fallback), "optional"),
        ("Respect robots", str(settings.respect_robots), "ok"),
    ]
    for name, value, status in checks:
        table.add_row(name, value, status)
    console.print(table)
    if not runtime.router:
        console.print(
            "[yellow]No usable model routes: deterministic planning/triage and source-only synthesis remain available.[/yellow]"
        )


@app.command()
def version() -> None:
    """Print version."""
    console.print(__version__)


def _score(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f}"
