from __future__ import annotations

import asyncio
import random
import shlex
from contextlib import suppress
from pathlib import Path

from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import CenterMiddle, Horizontal, Vertical
from textual.suggester import SuggestFromList
from textual.widgets import DataTable, Input, RichLog, Static

from traceweave import __version__
from traceweave.agent import PromptInterpreter
from traceweave.exporter import Exporter
from traceweave.models import ProgressEvent, ResearchSpec
from traceweave.providers.presets import preset_warnings
from traceweave.runtime import build_runtime

COMMANDS = [
    "/research ",
    "/angle ",
    "/mode quick",
    "/mode standard",
    "/mode deep",
    "/mode overnight",
    "/depth ",
    "/budget ",
    "/rounds ",
    "/language ",
    "/resume",
    "/pause",
    "/runs",
    "/sources",
    "/claims",
    "/frontier",
    "/archives",
    "/citations",
    "/entities",
    "/timeline",
    "/graph",
    "/media",
    "/observations",
    "/providers",
    "/providers sync",
    "/providers reload",
    "/dashboard",
    "/router",
    "/session list",
    "/session new ",
    "/session switch ",
    "/session rename ",
    "/vision on",
    "/vision off",
    "/vision budget ",
    "/export",
    "/export md",
    "/export json",
    "/export mermaid",
    "/export graphml",
    "/export evidence",
    "/shell status",
    "/shell enable",
    "/shell disable",
    "/clear",
    "/help",
    "/doctor",
    "/quit",
]

TIPS = [
    "[cyan]Tip[/cyan]  Use /angle to change what the research engine considers important.",
    "[magenta]Tip[/magenta]  Deep mode follows citations, archives, papers and high-value links.",
    "[green]Tip[/green]  Every discovery keeps its query, engine and retrieval provenance.",
    "[yellow]Tip[/yellow]  /providers sync refreshes token-scoped model catalogs without storing API keys.",
    "[blue]Tip[/blue]  /pause is durable; /resume continues the same run after a restart.",
    "[cyan]Tip[/cyan]  Prefix a command with ! to use the local shell after /shell enable.",
]

HELP = """[b]Research[/b]
/research TOPIC  /angle TEXT  /mode quick|standard|deep|overnight  /rounds N  /depth 0..5  /budget N  /language CODE
/resume [RUN]  /pause

[b]Evidence & graph[/b]
/sources [RUN]  /claims [RUN]  /frontier [RUN]  /archives [RUN]  /citations [RUN]
/entities [RUN]  /timeline [RUN]  /graph [RUN]  /media [RUN]  /observations [RUN]

[b]Providers[/b]
/providers  /providers sync  /providers reload  /router  /dashboard
Up to five keys/provider are read from .env; Cloudflare supports three account/token pairs.
/vision on|off  /vision budget N   (also requires TRACEWEAVE_REMOTE_VISION_ENABLED=true)

[b]Sessions & output[/b]
/session list|new NAME|switch ID|rename NAME
/export [RUN] [md|json|mermaid|graphml|evidence]

[b]Local shell[/b]
/shell status|enable|disable   !COMMAND

[b]Keys[/b]
Ctrl+L focus input · Ctrl+R resume · Ctrl+E export · Ctrl+K clear trace · Ctrl+Q quit · F1 help
Up/Down command history. Right-arrow accepts an autocomplete suggestion.
"""


class TraceWeaveApp(App):
    TITLE = "TraceWeave"
    SUB_TITLE = f"v{__version__}"
    CSS = """
    Screen { layout: vertical; background: $surface; }

    #landing { height: 1fr; }
    #launch-card { width: 76; max-width: 92%; height: auto; }
    #logo { height: 3; content-align: center middle; text-align: center; text-style: bold; color: $accent; }
    #launch-input { height: 3; border: round $primary; background: $panel; }
    #launch-meta { height: 1; margin-top: 1; content-align: center middle; text-align: center; color: $text-muted; }
    #tip { height: 2; margin-top: 1; content-align: center top; text-align: center; color: $text-muted; }

    #workspace { display: none; height: 1fr; }
    #topbar { height: 2; padding: 0 1; background: $panel; content-align: left middle; color: $text-muted; }
    #workbody { height: 1fr; }
    #provider-dashboard { display: none; height: 1fr; padding: 0 1; }
    #provider-summary { height: 2; color: $text-muted; }
    #provider-usage { height: 1fr; }
    #primary { width: 70%; padding: 0 1; }
    #side { width: 30%; padding: 0 1; background: $panel; }
    .heading { height: 1; text-style: bold; color: $accent; }
    #sources { height: 1fr; }
    #plan-wrap { height: 46%; min-height: 8; }
    #plan { height: 1fr; overflow-y: auto; color: $text; }
    #trace-wrap { height: 54%; min-height: 8; padding-top: 1; }
    #log { height: 1fr; }
    #command { display: none; height: 3; margin: 0 1; border: round $primary; background: $panel; }
    """
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=False),
        Binding("ctrl+l", "focus_command", "Input", show=False),
        Binding("ctrl+r", "resume_latest", "Resume", show=False),
        Binding("ctrl+e", "export_latest", "Export", show=False),
        Binding("ctrl+k", "clear_log", "Clear", show=False),
        Binding("f1", "help", "Help", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.runtime = build_runtime(callback=self._on_progress)
        session = self.runtime.storage.latest_session()
        if session is None:
            sid = self.runtime.storage.create_session(Path.cwd().name or "default")
            session = self.runtime.storage.get_session(sid)
        assert session is not None
        self.session_id = str(session["id"])
        self.current_run: str | None = session.get("active_run_id")
        self.angle = str(session.get("angle") or "")
        self.mode = str(session.get("mode") or "standard")
        self.language = str(session.get("language") or "all")
        self.rounds: int | None = None
        self.depth: int | None = None
        self.budget: int | None = None
        self.allow_remote_vision = False
        self.max_vision_calls = 0
        self.shell_enabled = bool(session.get("shell_enabled")) or self.runtime.settings.shell_enabled
        self._seen_source_ids: set[int] = set()
        self._history: list[str] = []
        self._history_index = 0
        self._landing = True
        self._tip = random.choice(TIPS)

    def compose(self) -> ComposeResult:
        with CenterMiddle(id="landing"), Vertical(id="launch-card"):
            yield Static(f"TRACEWEAVE  [dim]v{__version__}[/dim]", id="logo")
            yield Input(
                placeholder="Research anything…",
                id="launch-input",
                suggester=SuggestFromList(COMMANDS, case_sensitive=False),
            )
            yield Static("", id="launch-meta")
            yield Static(self._tip, id="tip")
        with Vertical(id="workspace"):
            yield Static("", id="topbar")
            with Horizontal(id="workbody"):
                with Vertical(id="primary"):
                    yield Static("SOURCES", classes="heading")
                    yield DataTable(id="sources", zebra_stripes=False, cursor_type="none")
                with Vertical(id="side"):
                    with Vertical(id="plan-wrap"):
                        yield Static("FOCUS", classes="heading")
                        yield Static("", id="plan")
                    with Vertical(id="trace-wrap"):
                        yield Static("ACTIVITY", classes="heading")
                        yield RichLog(id="log", wrap=True, highlight=True, markup=True)
            with Vertical(id="provider-dashboard"):
                yield Static("PROVIDER / MODEL USAGE", classes="heading")
                yield Static("", id="provider-summary")
                yield DataTable(id="provider-usage", zebra_stripes=False, cursor_type="none")
        yield Input(
            placeholder="Ask, /command, or !shell…",
            id="command",
            suggester=SuggestFromList(COMMANDS, case_sensitive=False),
        )

    def on_mount(self) -> None:
        table = self.query_one("#sources", DataTable)
        table.add_column("ID", key="id")
        table.add_column("Type", key="type")
        table.add_column("Imp", key="importance")
        table.add_column("Rel", key="relevance")
        table.add_column("Title", key="title")
        table.add_column("Domain", key="domain")
        usage = self.query_one("#provider-usage", DataTable)
        for label, key in (
            ("Provider", "provider"),
            ("Token", "credential"),
            ("Model", "model"),
            ("Req", "requests"),
            ("OK", "successes"),
            ("Fail", "failures"),
            ("Input", "prompt"),
            ("Output", "completion"),
            ("Total", "total"),
            ("Avg s", "latency"),
            ("Last", "last"),
        ):
            usage.add_column(label, key=key)
        self._refresh_landing_meta()
        self.query_one("#launch-input", Input).focus()
        if self.runtime.router:
            self.run_worker(
                self._sync_catalogs_background(),
                name="catalog-sync",
                group="catalog",
                exclusive=True,
                exit_on_error=False,
            )

    async def _sync_catalogs_background(self) -> None:
        assert self.runtime.router is not None
        await self.runtime.router.ensure_catalogs(force=False)
        self._refresh_landing_meta()
        self._update_status()

    def _route_label(self) -> str:
        route = self.runtime.router.primary_route("planning") if self.runtime.router else None
        if not route:
            return "deterministic / catalog discovery"
        tier = f" · {route['tier']}" if route.get("tier") else ""
        return f"{route['provider']} / {route['model']}{tier}"

    def _refresh_landing_meta(self) -> None:
        cwd = Path.cwd()
        folder = cwd.name or str(cwd)
        run_hint = f" · resume {self.current_run}" if self.current_run else ""
        self.query_one("#launch-meta", Static).update(
            f"[dim]📁 {folder}   ·   model[/dim] [b]{self._route_label()}[/b][dim]{run_hint}[/dim]"
        )

    def _update_status(self) -> None:
        if self._landing:
            self._refresh_landing_meta()
            return
        run = self.runtime.storage.get_run(self.current_run) if self.current_run else None
        round_text = f"r{run['current_round']}/{run['max_rounds']}" if run else "idle"
        tasks = self.runtime.storage.task_stats(self.current_run) if self.current_run else {}
        queue = f"done {tasks.get('completed', 0)} · queued {tasks.get('pending', 0) + tasks.get('retry', 0)}"
        self.query_one("#topbar", Static).update(
            f"[b]TraceWeave[/b]  ·  {round_text}  ·  {self.mode}  ·  {queue}  ·  run {self.current_run or '—'}"
        )

    def _show_workspace(self) -> None:
        self._landing = False
        self.query_one("#landing").styles.display = "none"
        self.query_one("#workspace").styles.display = "block"
        self.query_one("#command").styles.display = "block"
        self.query_one("#command", Input).focus()
        self._update_status()

    def _show_landing(self) -> None:
        self._landing = True
        self.query_one("#workspace").styles.display = "none"
        self.query_one("#command").styles.display = "none"
        self.query_one("#landing").styles.display = "block"
        self._tip = random.choice(TIPS)
        self.query_one("#tip", Static).update(self._tip)
        self._refresh_landing_meta()
        self.query_one("#launch-input", Input).focus()

    def _load_run_ui(self, run_id: str) -> None:
        run = self.runtime.storage.get_run(run_id)
        if not run:
            return
        self._show_workspace()
        plan = self.runtime.storage.get_plan(run_id, max(1, int(run.get("current_round") or 1)))
        if plan:
            self._render_plan(plan.objective, plan.focus, plan.queries, plan.gaps)
        table = self.query_one("#sources", DataTable)
        table.clear()
        self._seen_source_ids.clear()
        for source in self.runtime.storage.sources_for_run(run_id, 150):
            self._add_source_row(
                source.id,
                source.category,
                source.title or source.url,
                source.domain,
                source.importance,
                source.relevance,
            )

    def _render_plan(self, objective: str, focus: list[str], queries: list[str], gaps: list[str]) -> None:
        # Keep the side pane scannable: the full plan remains persisted in SQLite/export.
        lines = [f"[b]{objective[:260]}[/b]"]
        if focus:
            lines += ["", "[dim]Focus[/dim]"] + [f"• {x[:120]}" for x in focus[:3]]
        if gaps:
            lines += ["", "[dim]Gaps[/dim]"] + [f"? {x[:120]}" for x in gaps[:3]]
        if queries:
            lines += ["", f"[dim]{len(queries)} queued queries[/dim]"]
        self.query_one("#plan", Static).update("\n".join(lines))

    def _add_source_row(
        self,
        sid: int,
        category: str,
        title: str,
        domain: str,
        importance: float | None = None,
        relevance: float | None = None,
    ) -> None:
        table = self.query_one("#sources", DataTable)
        if sid in self._seen_source_ids:
            if importance is not None:
                table.update_cell(str(sid), "importance", _score(importance))
            if relevance is not None:
                table.update_cell(str(sid), "relevance", _score(relevance))
            return
        self._seen_source_ids.add(sid)
        table.add_row(
            f"S{sid}",
            category[:10],
            _score(importance),
            _score(relevance),
            title[:64],
            domain[:30],
            key=str(sid),
        )

    async def _on_progress(self, event: ProgressEvent) -> None:
        self._show_workspace()
        log = self.query_one("#log", RichLog)
        important = event.kind in {
            "plan.ready",
            "source.discovered",
            "source.triaged",
            "claim.extracted",
            "frontier.visit",
            "specialists.discovered",
            "archives.discovered",
            "graph.curated",
            "run.completed",
            "run.failed",
            "search.failed",
            "source.fetch_failed",
            "provider.catalog_failed",
        }
        if important:
            log.write(f"[dim]{event.kind}[/dim] {event.message}")
        if event.kind == "plan.ready":
            self._render_plan(
                str(event.data.get("objective", "")),
                list(event.data.get("focus", [])),
                list(event.data.get("queries", [])),
                list(event.data.get("gaps", [])),
            )
        elif event.kind == "source.discovered":
            sid = int(event.data["source_id"])
            self._add_source_row(
                sid,
                str(event.data.get("category", "web")),
                str(event.data.get("title") or event.data.get("url", "")),
                _domain(str(event.data.get("url", ""))),
            )
        elif event.kind == "source.triaged":
            sid = int(event.data["source_id"])
            if sid in self._seen_source_ids:
                table = self.query_one("#sources", DataTable)
                table.update_cell(str(sid), "importance", _score(float(event.data.get("importance", 0))))
                table.update_cell(str(sid), "relevance", _score(float(event.data.get("relevance", 0))))
        elif event.kind == "run.completed":
            self.notify("Research completed", severity="information", timeout=5)
        self._update_status()

    @on(Input.Submitted, "#launch-input")
    async def launch_submitted(self, event: Input.Submitted) -> None:
        await self._dispatch_input(event)

    @on(Input.Submitted, "#command")
    async def command_submitted(self, event: Input.Submitted) -> None:
        await self._dispatch_input(event)

    async def _dispatch_input(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        self._history.append(text)
        self._history = self._history[-100:]
        self._history_index = len(self._history)
        if text.startswith("!"):
            await self._run_shell(text[1:].strip())
        elif text.startswith("/"):
            await self._handle_command(text)
        else:
            self._start_research(text)

    async def on_key(self, event: events.Key) -> None:
        target = self.query_one("#launch-input" if self._landing else "#command", Input)
        if not target.has_focus or not self._history:
            return
        if event.key == "up":
            self._history_index = max(0, self._history_index - 1)
            target.value = self._history[self._history_index]
            target.cursor_position = len(target.value)
            event.stop()
        elif event.key == "down":
            self._history_index = min(len(self._history), self._history_index + 1)
            target.value = (
                "" if self._history_index == len(self._history) else self._history[self._history_index]
            )
            target.cursor_position = len(target.value)
            event.stop()

    async def _handle_command(self, text: str) -> None:
        try:
            parts = shlex.split(text)
        except ValueError as exc:
            self._show_workspace()
            self.query_one("#log", RichLog).write(f"[red]{exc}[/red]")
            return
        cmd, args = parts[0].lower(), parts[1:]
        log = self.query_one("#log", RichLog)
        if cmd == "/help":
            self._show_workspace()
            log.write(HELP)
        elif cmd == "/quit":
            self.exit()
        elif cmd == "/clear":
            log.clear()
        elif cmd == "/angle":
            self.angle = " ".join(args)
            self.runtime.storage.update_session(self.session_id, angle=self.angle)
            self.notify(f"Angle: {self.angle or 'none'}")
        elif cmd == "/mode" and args:
            if args[0] not in {"quick", "standard", "deep", "overnight"}:
                self.notify("Mode must be quick, standard, deep or overnight", severity="error")
            else:
                self.mode = args[0]
                self.runtime.storage.update_session(self.session_id, mode=self.mode)
                self.notify(f"Mode: {self.mode}")
        elif cmd == "/language" and args:
            self.language = args[0]
            self.runtime.storage.update_session(self.session_id, language=self.language)
        elif cmd in {"/depth", "/budget", "/rounds"} and args:
            try:
                value = _bounded_int(
                    args[0],
                    0 if cmd != "/rounds" else 1,
                    5 if cmd == "/depth" else (500 if cmd == "/budget" else 10),
                )
                if cmd == "/depth":
                    self.depth = value
                elif cmd == "/budget":
                    self.budget = value
                else:
                    self.rounds = value
            except ValueError:
                self.notify(f"Invalid {cmd[1:]} value", severity="error")
        elif cmd == "/research" and args:
            self._start_research(" ".join(args))
        elif cmd == "/resume":
            self._resume(args[0] if args else None)
        elif cmd == "/pause":
            self._pause_research()
        elif cmd == "/runs":
            self._show_workspace()
            for row in self.runtime.storage.list_runs(20):
                log.write(
                    f"[cyan]{row['id']}[/cyan] {row['status']:<9} {row['current_round']}/{row['max_rounds']}  {row['topic']}"
                )
        elif cmd in {
            "/sources",
            "/claims",
            "/archives",
            "/citations",
            "/entities",
            "/timeline",
            "/graph",
            "/frontier",
            "/media",
            "/observations",
        }:
            self._inspect(cmd, args)
        elif cmd == "/providers":
            await self._providers_command(args)
        elif cmd == "/dashboard":
            self._toggle_dashboard()
        elif cmd == "/vision":
            if args and args[0] == "on":
                self.allow_remote_vision = True
                if self.max_vision_calls <= 0:
                    self.max_vision_calls = 20
                self.notify(
                    f"Remote vision enabled for the next run (budget {self.max_vision_calls})",
                    severity="warning",
                )
            elif args and args[0] == "off":
                self.allow_remote_vision = False
                self.notify("Remote vision disabled")
            elif len(args) > 1 and args[0] == "budget":
                try:
                    self.max_vision_calls = _bounded_int(args[1], 0, 10_000)
                except ValueError:
                    self.notify("Invalid vision budget", severity="error")
            else:
                self.notify(
                    f"Remote vision is {'on' if self.allow_remote_vision else 'off'}; budget {self.max_vision_calls}"
                )
        elif cmd == "/router":
            self._show_workspace()
            for row in reversed(self.runtime.storage.router_attempts(30)):
                state = "green" if row["ok"] else "red"
                log.write(
                    f"[{state}]{'OK' if row['ok'] else 'FAIL'}[/{state}] {row['task']} {row['deployment_key']} {row['failure_kind'] or ''} {row['latency_seconds'] or 0:.2f}s"
                )
        elif cmd == "/export":
            rid = (
                args[0]
                if args
                and len(args[0]) >= 6
                and args[0] not in {"md", "json", "mermaid", "graphml", "evidence"}
                else self.current_run
            )
            fmt = (
                args[1]
                if len(args) > 1
                else (
                    args[0] if args and args[0] in {"md", "json", "mermaid", "graphml", "evidence"} else "md"
                )
            )
            self._export(rid, fmt)
        elif cmd == "/session":
            await self._session_command(args)
        elif cmd == "/shell":
            await self._shell_command(args)
        elif cmd == "/doctor":
            self._show_workspace()
            log.write(
                f"data={self.runtime.settings.data_dir.resolve()} db={self.runtime.settings.db_path.resolve()} routes={len(self.runtime.router.deployments) if self.runtime.router else 0}"
            )
            for warning in preset_warnings():
                log.write(f"[yellow]{warning}[/yellow]")
        else:
            self._show_workspace()
            log.write("[yellow]Unknown command. Use /help.[/yellow]")
        self._update_status()

    def _inspect(self, cmd: str, args: list[str]) -> None:
        self._show_workspace()
        log = self.query_one("#log", RichLog)
        rid = args[0] if args else self.current_run
        if not rid:
            log.write("[yellow]No run.[/yellow]")
            return
        if cmd == "/sources":
            for s in self.runtime.storage.sources_for_run(rid, 40):
                log.write(
                    f"S{s.id} I={_score(s.importance)} R={_score(s.relevance)} N={_score(s.novelty)} {s.title or s.url}"
                )
        elif cmd == "/claims":
            for c in self.runtime.storage.claims_for_run(rid, 50):
                log.write(f"C{c['id']} [S{c['source_id']}] {c['claim_text']}")
        elif cmd == "/frontier":
            log.write(str(self.runtime.storage.frontier_stats(rid)))
        elif cmd == "/archives":
            for x in self.runtime.storage.archive_captures_for_run(rid, 60):
                log.write(
                    f"A{x['id']} {x['engine']} {x['captured_at']} S{x['source_id']} {x['capture_url'][:100]}"
                )
        elif cmd == "/citations":
            for x in self.runtime.storage.citations_for_run(rid, 80):
                log.write(f"{x['kind']:<6} S{x['source_id']} → {x['target_url']}")
        elif cmd == "/entities":
            for x in self.runtime.storage.entities_for_run(rid, 80):
                log.write(
                    f"E{x['id']} {x['entity_type']:<12} {float(x['confidence']):.2f} {x['canonical_name']}"
                )
        elif cmd == "/timeline":
            for x in self.runtime.storage.timeline_for_run(rid, 80):
                log.write(f"{x['event_time']}  {x['label'][:140]} [S{x['source_id'] or 0}]")
        elif cmd == "/graph":
            log.write(
                f"entities={len(self.runtime.storage.entities_for_run(rid, 5000))} relationships={len(self.runtime.storage.relationships_for_run(rid, 5000))} research_edges={len(self.runtime.storage.research_edges_for_run(rid, 10000))}"
            )
        elif cmd == "/media":
            for x in self.runtime.storage.media_leads_for_run(rid, 100):
                log.write(
                    f"M{x['id']} {x['status']:<9} S{x['source_id']} {x['alt_text'][:60]} {x['url'][:100]}"
                )
        elif cmd == "/observations":
            for x in self.runtime.storage.observations_for_run(rid, 100):
                log.write(
                    f"O{x['id']} I={float(x['importance']):.0f} Rare={float(x['rarity']):.0f} {x['kind']} {x['value_text'][:120]}"
                )

    async def _providers_command(self, args: list[str]) -> None:
        self._show_workspace()
        log = self.query_one("#log", RichLog)
        if not self.runtime.router:
            log.write("[yellow]No provider credentials found in .env/providers.toml.[/yellow]")
            return
        if args and args[0] == "sync":
            result = await self.runtime.router.ensure_catalogs(force=True)
            self.runtime.router.reload()
            log.write(f"Catalog sync: {result or 'nothing to refresh'}")
        elif args and args[0] == "reload":
            log.write(f"Reloaded {self.runtime.router.reload()} routes")
        for row in self.runtime.router.status_rows("planning"):
            health = "green" if row["healthy"] else "yellow"
            log.write(
                f"[{health}]{row['provider']}:{row['credential']}[/{health}]  {row['model']}  ok={row['successes']} fail={row['failures']} cd={row['cooldown_seconds']}s lat={row['latency']}s"
            )
        for warning in preset_warnings():
            log.write(f"[yellow]{warning}[/yellow]")
        self._refresh_landing_meta()

    def _toggle_dashboard(self) -> None:
        self._show_workspace()
        dashboard = self.query_one("#provider-dashboard")
        workbody = self.query_one("#workbody")
        showing = dashboard.styles.display != "none"
        dashboard.styles.display = "none" if showing else "block"
        workbody.styles.display = "block" if showing else "none"
        if not showing:
            self._refresh_provider_dashboard()

    def _refresh_provider_dashboard(self) -> None:
        table = self.query_one("#provider-usage", DataTable)
        table.clear()
        rows = self.runtime.storage.provider_usage(run_id=None, limit=200)
        total_requests = sum(int(row.get("requests") or 0) for row in rows)
        total_tokens = sum(int(row.get("total_tokens") or 0) for row in rows)
        failures = sum(int(row.get("failures") or 0) for row in rows)
        route_count = len(self.runtime.router.deployments) if self.runtime.router else 0
        self.query_one("#provider-summary", Static).update(
            f"routes {route_count}  ·  requests {total_requests}  ·  tokens {total_tokens}  ·  failures {failures}  ·  run {self.current_run or 'all'}"
        )
        for index, row in enumerate(rows):
            table.add_row(
                str(row.get("provider_id") or ""),
                str(row.get("credential_id") or ""),
                str(row.get("model_id") or "")[:42],
                str(row.get("requests") or 0),
                str(row.get("successes") or 0),
                str(row.get("failures") or 0),
                str(row.get("prompt_tokens") or 0),
                str(row.get("completion_tokens") or 0),
                str(row.get("total_tokens") or 0),
                str(row.get("avg_latency") or 0),
                str(row.get("last_at") or "")[:19],
                key=f"usage-{index}",
            )

    async def _session_command(self, args: list[str]) -> None:
        action = args[0] if args else "list"
        if action == "list":
            self._show_workspace()
            log = self.query_one("#log", RichLog)
            for row in self.runtime.storage.list_sessions(30):
                marker = "*" if row["id"] == self.session_id else " "
                log.write(
                    f"{marker} [cyan]{row['id']}[/cyan] {row['name']} mode={row['mode']} run={row['active_run_id'] or '—'}"
                )
        elif action == "new":
            sid = self.runtime.storage.create_session(" ".join(args[1:]) or Path.cwd().name or "session")
            self._switch_session(sid)
            self.notify(f"Session {sid} created")
        elif action == "switch" and len(args) > 1:
            if self.runtime.storage.get_session(args[1]):
                self._switch_session(args[1])
                self.notify(f"Session {args[1]}")
            else:
                self.notify("Unknown session", severity="error")
        elif action == "rename" and len(args) > 1:
            self.runtime.storage.update_session(self.session_id, name=" ".join(args[1:]))
            self._refresh_landing_meta()
        else:
            self.notify("Use /session list|new NAME|switch ID|rename NAME", severity="warning")

    def _switch_session(self, sid: str) -> None:
        row = self.runtime.storage.get_session(sid)
        if not row:
            return
        self.session_id = sid
        self.current_run = row.get("active_run_id")
        self.angle = str(row.get("angle") or "")
        self.mode = str(row.get("mode") or "standard")
        self.language = str(row.get("language") or "all")
        self.shell_enabled = bool(row.get("shell_enabled"))
        self._show_landing()

    async def _shell_command(self, args: list[str]) -> None:
        action = args[0].lower() if args else "status"
        if action == "enable":
            self.shell_enabled = True
            self.runtime.storage.update_session(self.session_id, shell_enabled=True)
            self.notify("Local shell enabled", severity="warning")
        elif action == "disable":
            self.shell_enabled = False
            self.runtime.storage.update_session(self.session_id, shell_enabled=False)
            self.notify("Local shell disabled")
        else:
            self.notify(f"Local shell is {'enabled' if self.shell_enabled else 'disabled'}")

    async def _run_shell(self, command: str) -> None:
        self._show_workspace()
        log = self.query_one("#log", RichLog)
        if not self.shell_enabled:
            log.write("[yellow]Shell is disabled. Run /shell enable first.[/yellow]")
            return
        if not command:
            return
        log.write(f"[cyan]$ {command}[/cyan]")
        try:
            proc = await asyncio.create_subprocess_shell(
                command, cwd=str(Path.cwd()), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=self.runtime.settings.shell_timeout_seconds
            )
        except TimeoutError:
            with suppress(Exception):
                proc.kill()  # type: ignore[possibly-undefined]
            log.write("[red]Shell command timed out.[/red]")
            return
        log.write(
            stdout.decode(errors="replace")[-self.runtime.settings.shell_max_output_chars :]
            or f"[dim]exit {proc.returncode}[/dim]"
        )

    def _start_research(self, topic: str) -> None:
        self._show_workspace()
        inferred = PromptInterpreter.heuristic(topic)
        defaults = ResearchSpec(
            topic=topic,
            angle=self.angle or inferred.angle,
            mode=self.mode if self.mode != "standard" else inferred.mode,
            max_rounds=self.rounds,
            language=self.language if self.language != "all" else inferred.language,
            max_depth=self.depth,
            max_frontier_pages=self.budget,
            allow_remote_vision=self.allow_remote_vision,
            max_vision_calls=self.max_vision_calls,
        )
        self._seen_source_ids.clear()
        self.query_one("#sources", DataTable).clear()
        self.query_one("#plan", Static).update(f"[b]{topic[:220]}[/b]\n\n[dim]interpreting request…[/dim]")
        self._update_status()

        async def work() -> None:
            spec = await self.runtime.engine.interpreter.resolve(topic, defaults=defaults)
            run_id = self.runtime.storage.create_run(spec)
            self.runtime.storage.event(
                run_id, "run.created", f"Created research run {run_id}", {"topic": spec.topic}
            )
            self.current_run = run_id
            self.mode = spec.mode
            self.language = spec.language
            self.angle = spec.angle
            self.runtime.storage.update_session(
                self.session_id,
                active_run_id=run_id,
                onboarding_complete=True,
                angle=spec.angle,
                mode=spec.mode,
                language=spec.language,
            )
            self.query_one("#plan", Static).update(
                f"[b]{spec.topic[:220]}[/b]\n\n[dim]{spec.mode} · {spec.language} · planning…[/dim]"
            )
            await self.runtime.engine.resume(run_id)
            self._update_status()

        self.run_worker(work(), name="research", group="research", exclusive=True, exit_on_error=False)

    def _pause_research(self) -> None:
        self._show_workspace()
        log = self.query_one("#log", RichLog)
        cancelled = self.workers.cancel_group(self, "research")
        log.write(
            "[yellow]Pause requested; use /resume to continue.[/yellow]"
            if cancelled
            else "[dim]No active research worker.[/dim]"
        )

    def _resume(self, run_id: str | None) -> None:
        run_id = run_id or self.current_run or _latest_id(self.runtime.storage)
        if not run_id:
            self.notify("No run to resume", severity="warning")
            return
        self.current_run = run_id
        self.runtime.storage.update_session(self.session_id, active_run_id=run_id)
        self._load_run_ui(run_id)

        async def work() -> None:
            await self.runtime.engine.resume(run_id)

        self.run_worker(work(), name="resume", group="research", exclusive=True, exit_on_error=False)

    def _export(self, run_id: str | None, fmt: str = "md") -> None:
        self._show_workspace()
        log = self.query_one("#log", RichLog)
        if not run_id:
            log.write("[yellow]No run to export.[/yellow]")
            return
        exporter = Exporter(self.runtime.storage, self.runtime.settings.data_dir / "exports")
        try:
            path = {
                "md": exporter.markdown,
                "json": exporter.json,
                "mermaid": exporter.mermaid,
                "graphml": exporter.graphml,
                "evidence": exporter.evidence,
            }[fmt](run_id)
        except (KeyError, ValueError) as exc:
            log.write(f"[red]{exc}[/red]")
            return
        log.write(f"[green]Exported:[/green] {path}")

    def action_focus_command(self) -> None:
        self.query_one("#launch-input" if self._landing else "#command", Input).focus()

    def action_resume_latest(self) -> None:
        self._resume(None)

    def action_export_latest(self) -> None:
        self._export(self.current_run or _latest_id(self.runtime.storage), "md")

    def action_clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()

    def action_help(self) -> None:
        self._show_workspace()
        self.query_one("#log", RichLog).write(HELP)


def _latest_id(storage) -> str | None:
    row = storage.latest_run()
    return row["id"] if row else None


def _domain(url: str) -> str:
    from urllib.parse import urlsplit

    return (urlsplit(url).hostname or "")[:30]


def _bounded_int(value: str, low: int, high: int) -> int:
    number = int(value)
    if not low <= number <= high:
        raise ValueError
    return number


def _score(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f}"
