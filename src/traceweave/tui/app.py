from __future__ import annotations

import shlex

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Input, RichLog, Static

from traceweave.exporter import Exporter
from traceweave.models import ProgressEvent, ResearchSpec
from traceweave.runtime import build_runtime

HELP = """[b]Commands[/b]
/research TOPIC     start a research run
/angle TEXT         set research angle
/mode MODE          quick | standard | deep
/rounds N           set round override
/resume [RUN_ID]    resume a run (latest if omitted)
/runs               show recent runs in the log
/export [RUN_ID]    export Markdown
/clear              clear log
/help               show this help
/quit               quit

[b]Shortcuts[/b]
Ctrl+L focus command line   Ctrl+R resume latest
Ctrl+E export latest        Ctrl+K clear log
Ctrl+Q quit                 Ctrl+P Textual command palette
"""


class TraceWeaveApp(App):
    TITLE = "TraceWeave"
    SUB_TITLE = "iterative research · v0.1"
    CSS = """
    Screen { layout: vertical; }
    #body { height: 1fr; }
    #left { width: 30%; border: round $accent; padding: 0 1; }
    #center { width: 44%; border: round $primary; padding: 0 1; }
    #right { width: 26%; border: round $secondary; padding: 0 1; }
    #plan { height: 1fr; overflow-y: auto; }
    #sources { height: 1fr; }
    #log { height: 1fr; }
    #command { dock: bottom; margin: 0 1 0 1; }
    .heading { text-style: bold; color: $accent; height: 1; }
    """
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+l", "focus_command", "Command"),
        Binding("ctrl+r", "resume_latest", "Resume"),
        Binding("ctrl+e", "export_latest", "Export"),
        Binding("ctrl+k", "clear_log", "Clear log"),
        Binding("f1", "help", "Help"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.runtime = build_runtime(callback=self._on_progress)
        self.current_run: str | None = None
        self.angle = ""
        self.mode = "standard"
        self.rounds: int | None = None
        self._seen_source_ids: set[int] = set()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield Static("PLAN / STATE", classes="heading")
                yield Static("Ready. Type a topic below or /help.", id="plan")
            with Vertical(id="center"):
                yield Static("SOURCES", classes="heading")
                yield DataTable(id="sources", zebra_stripes=True)
            with Vertical(id="right"):
                yield Static("LIVE TRACE", classes="heading")
                yield RichLog(id="log", wrap=True, highlight=True, markup=True)
        yield Input(placeholder="Research topic, or /help …", id="command")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#sources", DataTable)
        table.add_columns("ID", "Type", "Title", "Domain")
        self.query_one("#command", Input).focus()
        self.query_one("#log", RichLog).write("[green]TraceWeave ready.[/green] Built-in Ctrl+P opens the command palette.")

    async def _on_progress(self, event: ProgressEvent) -> None:
        log = self.query_one("#log", RichLog)
        log.write(f"[dim]{event.kind}[/dim] {event.message}")
        if event.kind == "plan.ready":
            queries = "\n".join(f"  • {q}" for q in event.data.get("queries", []))
            focus = ", ".join(event.data.get("focus", []))
            self.query_one("#plan", Static).update(
                f"[b]{event.data.get('objective', '')}[/b]\n\nFocus: {focus}\n\nQueries:\n{queries}"
            )
        elif event.kind == "source.discovered":
            sid = int(event.data["source_id"])
            if sid not in self._seen_source_ids:
                self._seen_source_ids.add(sid)
                self.query_one("#sources", DataTable).add_row(
                    f"S{sid}",
                    str(event.data.get("category", "web")),
                    str(event.data.get("title") or event.data.get("url", ""))[:55],
                    _domain(str(event.data.get("url", ""))),
                )
        elif event.kind == "run.completed":
            self.notify("Research completed", severity="information", timeout=5)

    @on(Input.Submitted, "#command")
    async def command_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            await self._handle_command(text)
        else:
            self._start_research(text)

    async def _handle_command(self, text: str) -> None:
        log = self.query_one("#log", RichLog)
        try:
            parts = shlex.split(text)
        except ValueError as exc:
            log.write(f"[red]{exc}[/red]")
            return
        cmd = parts[0].lower()
        args = parts[1:]
        if cmd == "/help":
            log.write(HELP)
        elif cmd == "/quit":
            self.exit()
        elif cmd == "/clear":
            log.clear()
        elif cmd == "/angle":
            self.angle = " ".join(args)
            log.write(f"Angle = [cyan]{self.angle or 'none'}[/cyan]")
        elif cmd == "/mode" and args:
            if args[0] not in {"quick", "standard", "deep"}:
                log.write("[red]Mode must be quick, standard, or deep.[/red]")
            else:
                self.mode = args[0]
                log.write(f"Mode = [cyan]{self.mode}[/cyan]")
        elif cmd == "/rounds" and args:
            try:
                value = int(args[0])
                if value < 1 or value > 8:
                    raise ValueError
                self.rounds = value
                log.write(f"Rounds = [cyan]{value}[/cyan]")
            except ValueError:
                log.write("[red]Rounds must be 1..8.[/red]")
        elif cmd == "/research" and args:
            self._start_research(" ".join(args))
        elif cmd == "/resume":
            run_id = args[0] if args else None
            self._resume(run_id)
        elif cmd == "/runs":
            for row in self.runtime.storage.list_runs(15):
                log.write(f"[cyan]{row['id']}[/cyan] {row['status']:<9} {row['current_round']}/{row['max_rounds']}  {row['topic']}")
        elif cmd == "/export":
            run_id = args[0] if args else self.current_run or _latest_id(self.runtime.storage)
            if run_id:
                path = Exporter(self.runtime.storage, self.runtime.settings.data_dir / "exports").markdown(run_id)
                log.write(f"[green]Exported:[/green] {path}")
            else:
                log.write("[yellow]No run to export.[/yellow]")
        else:
            log.write("[yellow]Unknown command. Use /help.[/yellow]")

    def _start_research(self, topic: str) -> None:
        spec = ResearchSpec(topic=topic, angle=self.angle, mode=self.mode, max_rounds=self.rounds)
        self._seen_source_ids.clear()
        self.query_one("#sources", DataTable).clear()
        self.query_one("#plan", Static).update(f"Starting: [b]{topic}[/b]")

        async def work() -> None:
            self.current_run = await self.runtime.engine.start(spec)

        self.run_worker(work(), name="research", group="research", exclusive=True, exit_on_error=False)

    def _resume(self, run_id: str | None) -> None:
        run_id = run_id or self.current_run or _latest_id(self.runtime.storage)
        if not run_id:
            self.query_one("#log", RichLog).write("[yellow]No run to resume.[/yellow]")
            return
        self.current_run = run_id

        async def work() -> None:
            await self.runtime.engine.resume(run_id)

        self.run_worker(work(), name="resume", group="research", exclusive=True, exit_on_error=False)

    def action_focus_command(self) -> None:
        self.query_one("#command", Input).focus()

    def action_resume_latest(self) -> None:
        self._resume(None)

    def action_export_latest(self) -> None:
        run_id = self.current_run or _latest_id(self.runtime.storage)
        if run_id:
            path = Exporter(self.runtime.storage, self.runtime.settings.data_dir / "exports").markdown(run_id)
            self.query_one("#log", RichLog).write(f"[green]Exported:[/green] {path}")

    def action_clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()

    def action_help(self) -> None:
        self.query_one("#log", RichLog).write(HELP)


def _latest_id(storage) -> str | None:
    row = storage.latest_run()
    return row["id"] if row else None


def _domain(url: str) -> str:
    from urllib.parse import urlsplit
    return (urlsplit(url).hostname or "")[:32]
