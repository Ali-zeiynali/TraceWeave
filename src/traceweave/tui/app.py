from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.suggester import SuggestFromList
from textual.widgets import DataTable, Header, Input, RichLog, Static

from traceweave import __version__
from traceweave.exporter import Exporter
from traceweave.models import ProgressEvent, ResearchSpec
from traceweave.runtime import build_runtime

COMMANDS = [
    "/research ", "/angle ", "/mode quick", "/mode standard", "/mode deep", "/depth ", "/budget ",
    "/language ", "/resume", "/pause", "/runs", "/sources", "/claims", "/frontier", "/providers", "/router",
    "/session list", "/session new ", "/session switch ", "/session rename ",
    "/export", "/export  md", "/export  json", "/export  mermaid", "/export  evidence",
    "/shell status", "/shell enable", "/shell disable", "/clear", "/help", "/doctor", "/quit",
]

HELP = """[b]Research[/b]
/research TOPIC        start a new iterative run
/angle TEXT            prioritization lens (saved in session)
/mode MODE             quick | standard | deep
/depth N               recursive frontier depth 0..5
/budget N              max best-first frontier pages for this run
/language CODE         search language or all
/resume [RUN_ID]       resume durable state
/pause                 cancel active research worker; durable state remains resumable

[b]Inspect[/b]
/runs                   recent runs
/sources [RUN_ID]       top sources and triage scores
/claims [RUN_ID]        grounded claims
/frontier [RUN_ID]      frontier queue stats
/providers              deployment/token/model health
/router                 recent routing attempts
/export [RUN] [FORMAT]  md | json | mermaid | evidence

[b]Sessions[/b]
/session list
/session new NAME
/session switch ID
/session rename NAME

[b]Local shell[/b]
/shell status|enable|disable
!COMMAND                run a local shell command when enabled

[b]UI[/b]
Ctrl+L command   Ctrl+R resume   Ctrl+E export   Ctrl+K clear trace
Ctrl+Q quit      Ctrl+P Textual command palette   F1 help
Up/Down command history. Right-arrow accepts completion suggestions.
"""

ONBOARDING = f"""[b]TraceWeave {__version__}[/b]

Evidence-first iterative research:
[b]PLAN → SEARCH → ASSESS → RE-PLAN → SEARCH[/b]

Start by typing a topic below, or use:
  [cyan]/research your question[/cyan]
  [cyan]/angle technical infrastructure[/cyan]
  [cyan]/mode deep[/cyan]

Useful setup:
  [cyan]/providers[/cyan]    inspect model/token routes
  [cyan]/help[/cyan]         all commands

Sources are persisted before fetch; fetched snapshots, triage, claims,
frontier state, provider health and session state survive restarts.
"""


class TraceWeaveApp(App):
    TITLE = "TraceWeave"
    SUB_TITLE = f"evidence-first research · v{__version__}"
    CSS = """
    Screen { layout: vertical; background: $surface; }
    Header { height: 1; }
    #status { height: 1; padding: 0 1; color: $text-muted; background: $panel; }
    #main { height: 1fr; }
    #onboarding { width: 72; max-width: 90%; height: auto; margin: 3 0; padding: 1 2; border: round $primary; align-horizontal: center; }
    #workspace { display: none; height: 1fr; }
    #left { width: 31%; padding: 0 1; border-right: solid $panel-lighten-1; }
    #center { width: 45%; padding: 0 1; }
    #right { width: 24%; padding: 0 1; border-left: solid $panel-lighten-1; }
    #plan { height: 1fr; overflow-y: auto; }
    #sources { height: 1fr; }
    #log { height: 1fr; }
    #command { dock: bottom; margin: 0 1; border: tall $primary; }
    .heading { text-style: bold; color: $accent; height: 1; margin-bottom: 1; }
    """
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=False),
        Binding("ctrl+l", "focus_command", "Command", show=False),
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
            sid = self.runtime.storage.create_session("default")
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
        self.shell_enabled = bool(session.get("shell_enabled")) or self.runtime.settings.shell_enabled
        self._seen_source_ids: set[int] = set()
        self._history: list[str] = []
        self._history_index = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="status")
        with Vertical(id="main"):
            yield Static(ONBOARDING, id="onboarding")
            with Horizontal(id="workspace"):
                with Vertical(id="left"):
                    yield Static("PLAN / GAPS", classes="heading")
                    yield Static("", id="plan")
                with Vertical(id="center"):
                    yield Static("SOURCES / EVIDENCE", classes="heading")
                    yield DataTable(id="sources", zebra_stripes=False, cursor_type="none")
                with Vertical(id="right"):
                    yield Static("TRACE", classes="heading")
                    yield RichLog(id="log", wrap=True, highlight=True, markup=True)
        yield Input(
            placeholder="Ask a research question, /help, or !shell-command …",
            id="command", suggester=SuggestFromList(COMMANDS, case_sensitive=False),
        )

    def on_mount(self) -> None:
        table = self.query_one("#sources", DataTable)
        table.add_columns("ID", "Type", "Imp", "Rel", "Title", "Domain")
        self.query_one("#command", Input).focus()
        self._update_status()
        if self.current_run:
            self._show_workspace()
            self._load_run_ui(self.current_run)

    def _update_status(self) -> None:
        route_count = len(self.runtime.router.deployments) if self.runtime.router else 0
        run = self.current_run or "—"
        shell = "on" if self.shell_enabled else "off"
        self.query_one("#status", Static).update(
            f"session {self.session_id} · mode {self.mode} · angle {self.angle or 'none'} · routes {route_count} · shell {shell} · run {run}"
        )

    def _show_workspace(self) -> None:
        self.query_one("#onboarding").styles.display = "none"
        self.query_one("#workspace").styles.display = "block"

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
            self._add_source_row(source.id, source.category, source.title or source.url, source.domain,
                                 source.importance, source.relevance)

    def _render_plan(self, objective: str, focus: list[str], queries: list[str], gaps: list[str]) -> None:
        q = "\n".join(f"  • {x}" for x in queries)
        g = "\n".join(f"  ? {x}" for x in gaps) or "  —"
        self.query_one("#plan", Static).update(
            f"[b]{objective}[/b]\n\n[dim]Focus[/dim]\n" + "\n".join(f"  • {x}" for x in focus) +
            f"\n\n[dim]Queries[/dim]\n{q}\n\n[dim]Gaps[/dim]\n{g}"
        )

    def _add_source_row(self, sid: int, category: str, title: str, domain: str,
                        importance: float | None = None, relevance: float | None = None) -> None:
        if sid in self._seen_source_ids:
            # DataTable updates are intentionally avoided here; full reload after triage keeps code stable.
            return
        self._seen_source_ids.add(sid)
        self.query_one("#sources", DataTable).add_row(
            f"S{sid}", category[:8], f"{importance:.0f}" if importance is not None else "—",
            f"{relevance:.0f}" if relevance is not None else "—", title[:48], domain[:28],
        )

    async def _on_progress(self, event: ProgressEvent) -> None:
        self._show_workspace()
        log = self.query_one("#log", RichLog)
        important = event.kind in {
            "plan.ready", "source.discovered", "source.triaged", "claim.extracted", "frontier.visit",
            "run.completed", "run.failed", "search.failed", "source.fetch_failed",
        }
        if important:
            log.write(f"[dim]{event.kind}[/dim] {event.message}")
        if event.kind == "plan.ready":
            self._render_plan(
                str(event.data.get("objective", "")), list(event.data.get("focus", [])),
                list(event.data.get("queries", [])), list(event.data.get("gaps", [])),
            )
        elif event.kind == "source.discovered":
            sid = int(event.data["source_id"])
            self._add_source_row(
                sid, str(event.data.get("category", "web")), str(event.data.get("title") or event.data.get("url", "")),
                _domain(str(event.data.get("url", ""))),
            )
        elif event.kind == "source.triaged" and self.current_run:
            # Reload to display sorted scores after analysis.
            self._load_run_ui(self.current_run)
        elif event.kind == "run.completed":
            self.notify("Research completed", severity="information", timeout=5)
        self._update_status()

    @on(Input.Submitted, "#command")
    async def command_submitted(self, event: Input.Submitted) -> None:
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
        command = self.query_one("#command", Input)
        if not command.has_focus or not self._history:
            return
        if event.key == "up":
            self._history_index = max(0, self._history_index - 1)
            command.value = self._history[self._history_index]
            command.cursor_position = len(command.value)
            event.stop()
        elif event.key == "down":
            self._history_index = min(len(self._history), self._history_index + 1)
            command.value = "" if self._history_index == len(self._history) else self._history[self._history_index]
            command.cursor_position = len(command.value)
            event.stop()

    async def _handle_command(self, text: str) -> None:
        log = self.query_one("#log", RichLog)
        try:
            parts = shlex.split(text)
        except ValueError as exc:
            self._show_workspace(); log.write(f"[red]{exc}[/red]"); return
        cmd, args = parts[0].lower(), parts[1:]
        if cmd == "/help":
            self._show_workspace(); log.write(HELP)
        elif cmd == "/quit":
            self.exit()
        elif cmd == "/clear":
            log.clear()
        elif cmd == "/angle":
            self.angle = " ".join(args)
            self.runtime.storage.update_session(self.session_id, angle=self.angle)
            log.write(f"Angle = [cyan]{self.angle or 'none'}[/cyan]")
        elif cmd == "/mode" and args:
            if args[0] not in {"quick", "standard", "deep"}:
                log.write("[red]Mode must be quick, standard, or deep.[/red]")
            else:
                self.mode = args[0]; self.runtime.storage.update_session(self.session_id, mode=self.mode)
        elif cmd == "/language" and args:
            self.language = args[0]; self.runtime.storage.update_session(self.session_id, language=self.language)
        elif cmd == "/depth" and args:
            try:
                self.depth = _bounded_int(args[0], 0, 5)
            except ValueError:
                log.write("[red]Depth must be 0..5.[/red]")
        elif cmd == "/budget" and args:
            try:
                self.budget = _bounded_int(args[0], 0, 500)
            except ValueError:
                log.write("[red]Budget must be 0..500 frontier pages.[/red]")
        elif cmd == "/rounds" and args:
            try:
                self.rounds = _bounded_int(args[0], 1, 10)
            except ValueError:
                log.write("[red]Rounds must be 1..10.[/red]")
        elif cmd == "/research" and args:
            self._start_research(" ".join(args))
        elif cmd == "/resume":
            self._resume(args[0] if args else None)
        elif cmd == "/pause":
            self._pause_research()
        elif cmd == "/runs":
            self._show_workspace()
            for row in self.runtime.storage.list_runs(20):
                log.write(f"[cyan]{row['id']}[/cyan] {row['status']:<9} {row['current_round']}/{row['max_rounds']}  {row['topic']}")
        elif cmd == "/sources":
            rid = args[0] if args else self.current_run
            if rid:
                for s in self.runtime.storage.sources_for_run(rid, 30):
                    log.write(f"S{s.id} I={_score(s.importance)} R={_score(s.relevance)} N={_score(s.novelty)} {s.title or s.url}")
        elif cmd == "/claims":
            rid = args[0] if args else self.current_run
            if rid:
                for c in self.runtime.storage.claims_for_run(rid, 40):
                    log.write(f"C{c['id']} [S{c['source_id']}] {c['claim_text']}")
        elif cmd == "/frontier":
            rid = args[0] if args else self.current_run
            log.write(str(self.runtime.storage.frontier_stats(rid)) if rid else "[yellow]No run.[/yellow]")
        elif cmd == "/providers":
            self._show_workspace()
            if args and args[0] == "reload" and self.runtime.router:
                count = self.runtime.router.reload(); log.write(f"Reloaded provider config: {count} usable routes")
            if not self.runtime.router:
                log.write("[yellow]No usable provider routes. Configure providers.toml + token env vars.[/yellow]")
            else:
                for row in self.runtime.router.status_rows():
                    health = "green" if row["healthy"] else "yellow"
                    log.write(
                        f"[{health}]{row['provider']}:{row['credential']}:{row['model']}[/{health}] "
                        f"{row['driver']} ok={row['successes']} fail={row['failures']} cooldown={row['cooldown_seconds']}s "
                        f"lat={row['latency']}s tasks={row['tasks']}"
                    )
        elif cmd == "/router":
            self._show_workspace()
            for row in reversed(self.runtime.storage.router_attempts(30)):
                state = "green" if row["ok"] else "red"
                log.write(
                    f"[{state}]{'OK' if row['ok'] else 'FAIL'}[/{state}] {row['task']} {row['deployment_key']} "
                    f"{row['failure_kind'] or ''} {row['latency_seconds'] or 0:.2f}s"
                )
        elif cmd == "/export":
            rid = args[0] if args and len(args[0]) >= 6 else self.current_run
            fmt = args[1] if len(args) > 1 else (args[0] if args and args[0] in {"md", "json", "mermaid", "evidence"} else "md")
            self._export(rid, fmt)
        elif cmd == "/session":
            await self._session_command(args)
        elif cmd == "/shell":
            await self._shell_command(args)
        elif cmd == "/doctor":
            self._show_workspace()
            log.write(f"data={self.runtime.settings.data_dir.resolve()} db={self.runtime.settings.db_path.resolve()} routes={len(self.runtime.router.deployments) if self.runtime.router else 0}")
        else:
            self._show_workspace(); log.write("[yellow]Unknown command. Use /help.[/yellow]")
        self._update_status()

    async def _session_command(self, args: list[str]) -> None:
        log = self.query_one("#log", RichLog); self._show_workspace()
        action = args[0] if args else "list"
        if action == "list":
            for row in self.runtime.storage.list_sessions(30):
                marker = "*" if row["id"] == self.session_id else " "
                log.write(f"{marker} [cyan]{row['id']}[/cyan] {row['name']} mode={row['mode']} run={row['active_run_id'] or '—'}")
        elif action == "new":
            sid = self.runtime.storage.create_session(" ".join(args[1:]) or "session")
            self._switch_session(sid); log.write(f"Created session {sid}")
        elif action == "switch" and len(args) > 1:
            if self.runtime.storage.get_session(args[1]):
                self._switch_session(args[1]); log.write(f"Switched to {args[1]}")
            else:
                log.write("[red]Unknown session.[/red]")
        elif action == "rename" and len(args) > 1:
            self.runtime.storage.update_session(self.session_id, name=" ".join(args[1:]))
        else:
            log.write("[yellow]Use /session list|new NAME|switch ID|rename NAME[/yellow]")

    def _switch_session(self, sid: str) -> None:
        row = self.runtime.storage.get_session(sid)
        if not row:
            return
        self.session_id = sid; self.current_run = row.get("active_run_id")
        self.angle = str(row.get("angle") or ""); self.mode = str(row.get("mode") or "standard")
        self.language = str(row.get("language") or "all"); self.shell_enabled = bool(row.get("shell_enabled"))
        if self.current_run:
            self._load_run_ui(self.current_run)

    async def _shell_command(self, args: list[str]) -> None:
        log = self.query_one("#log", RichLog); self._show_workspace()
        action = args[0].lower() if args else "status"
        if action == "enable":
            self.shell_enabled = True; self.runtime.storage.update_session(self.session_id, shell_enabled=True)
            log.write("[yellow]Local shell enabled for this session. Commands run with this TraceWeave process user's permissions.[/yellow]")
        elif action == "disable":
            self.shell_enabled = False; self.runtime.storage.update_session(self.session_id, shell_enabled=False)
            log.write("Local shell disabled.")
        else:
            log.write(f"Local shell is {'enabled' if self.shell_enabled else 'disabled'}. Use !COMMAND when enabled.")

    async def _run_shell(self, command: str) -> None:
        self._show_workspace(); log = self.query_one("#log", RichLog)
        if not self.shell_enabled:
            log.write("[yellow]Shell is disabled. Run /shell enable first.[/yellow]"); return
        if not command:
            return
        log.write(f"[cyan]$ {command}[/cyan]")
        try:
            proc = await asyncio.create_subprocess_shell(
                command, cwd=str(Path.cwd()), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self.runtime.settings.shell_timeout_seconds)
        except asyncio.TimeoutError:
            try:
                proc.kill()  # type: ignore[possibly-undefined]
            except Exception:
                pass
            log.write("[red]Shell command timed out.[/red]"); return
        text = stdout.decode(errors="replace")[-self.runtime.settings.shell_max_output_chars:]
        log.write(text or f"[dim]exit {proc.returncode}[/dim]")

    def _start_research(self, topic: str) -> None:
        self._show_workspace()
        spec = ResearchSpec(
            topic=topic, angle=self.angle, mode=self.mode, max_rounds=self.rounds, language=self.language,
            max_depth=self.depth, max_frontier_pages=self.budget,
        )
        # Create the durable run synchronously before starting the background worker. This means
        # the session knows the run id immediately and can recover it even if the TUI is closed mid-run.
        run_id = self.runtime.storage.create_run(spec)
        self.runtime.storage.event(run_id, "run.created", f"Created research run {run_id}", {"topic": spec.topic})
        self.current_run = run_id
        self.runtime.storage.update_session(
            self.session_id, active_run_id=run_id, onboarding_complete=True, angle=self.angle,
            mode=self.mode, language=self.language,
        )
        self._seen_source_ids.clear(); self.query_one("#sources", DataTable).clear()
        self.query_one("#plan", Static).update(f"Starting: [b]{topic}[/b]\n\nRun: [cyan]{run_id}[/cyan]")
        self._update_status()

        async def work() -> None:
            await self.runtime.engine.resume(run_id)
            self._update_status()

        self.run_worker(work(), name="research", group="research", exclusive=True, exit_on_error=False)

    def _pause_research(self) -> None:
        self._show_workspace()
        log = self.query_one("#log", RichLog)
        cancelled = self.workers.cancel_group(self, "research")
        if cancelled:
            log.write("[yellow]Pause requested. The engine will commit paused state; use /resume to continue.[/yellow]")
        else:
            log.write("[dim]No active research worker.[/dim]")

    def _resume(self, run_id: str | None) -> None:
        run_id = run_id or self.current_run or _latest_id(self.runtime.storage)
        if not run_id:
            self._show_workspace(); self.query_one("#log", RichLog).write("[yellow]No run to resume.[/yellow]"); return
        self.current_run = run_id; self.runtime.storage.update_session(self.session_id, active_run_id=run_id)
        self._load_run_ui(run_id)

        async def work() -> None:
            await self.runtime.engine.resume(run_id)

        self.run_worker(work(), name="resume", group="research", exclusive=True, exit_on_error=False)

    def _export(self, run_id: str | None, fmt: str = "md") -> None:
        self._show_workspace(); log = self.query_one("#log", RichLog)
        if not run_id:
            log.write("[yellow]No run to export.[/yellow]"); return
        exporter = Exporter(self.runtime.storage, self.runtime.settings.data_dir / "exports")
        try:
            path = {"md": exporter.markdown, "json": exporter.json, "mermaid": exporter.mermaid,
                    "evidence": exporter.evidence}[fmt](run_id)
        except (KeyError, ValueError) as exc:
            log.write(f"[red]{exc}[/red]"); return
        log.write(f"[green]Exported:[/green] {path}")

    def action_focus_command(self) -> None:
        self.query_one("#command", Input).focus()

    def action_resume_latest(self) -> None:
        self._resume(None)

    def action_export_latest(self) -> None:
        self._export(self.current_run or _latest_id(self.runtime.storage), "md")

    def action_clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()

    def action_help(self) -> None:
        self._show_workspace(); self.query_one("#log", RichLog).write(HELP)


def _latest_id(storage) -> str | None:
    row = storage.latest_run(); return row["id"] if row else None


def _domain(url: str) -> str:
    from urllib.parse import urlsplit
    return (urlsplit(url).hostname or "")[:28]


def _bounded_int(value: str, low: int, high: int) -> int:
    number = int(value)
    if not low <= number <= high:
        raise ValueError
    return number


def _score(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f}"
