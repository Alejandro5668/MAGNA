from __future__ import annotations
import os
from pathlib import Path

from textual.app import App, ComposeResult
from textual.screen import Screen, ModalScreen
from textual.widgets import Static, Input, Label
from textual.containers import Container, Vertical, Horizontal
from textual.binding import Binding
from textual import work


# ─── Shared terminal utilities ────────────────────────────────────────────────

def _q_style():
    from questionary import Style
    return Style([
        ("qmark",       "fg:cyan bold"),
        ("question",    "fg:white bold"),
        ("pointer",     "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),
        ("selected",    "fg:cyan"),
        ("answer",      "fg:cyan bold"),
    ])


def _capture_clipboard() -> str | None:
    import subprocess
    from datetime import datetime
    folder = Path.home() / ".mycontext" / "evidencias"
    name = f"captura_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    path = (folder / name).resolve()
    ps_path = str(path).replace("\\", "/")
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        f"$img = [System.Windows.Forms.Clipboard]::GetImage(); "
        f"if ($img) {{ $img.Save('{ps_path}', [System.Drawing.Imaging.ImageFormat]::Png); exit 0 }} "
        "else { exit 1 }"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, timeout=10,
        )
        if r.returncode == 0 and path.exists():
            return str(path)
    except Exception:
        pass
    return None


def _ask_image() -> str | None:
    """Clipboard-first image prompt — runs inside suspend context."""
    import questionary
    from rich.console import Console
    console = Console()
    style = _q_style()

    use_cb = questionary.confirm(
        "  ¿Tenés una captura en el portapapeles?",
        default=False,
        style=style,
    ).ask()

    if use_cb:
        captured = _capture_clipboard()
        if captured:
            console.print(f"  [bold green]✔[/bold green] [dim]Guardada: {captured}[/dim]")
            return captured
        console.print("  [bold yellow]⚠[/bold yellow] [dim]No hay imagen en el portapapeles.[/dim]")

    manual = questionary.text("  Ruta de imagen (Enter para omitir)", style=style).ask()
    return manual.strip() if manual and manual.strip() else None


# ─── Input Modal ──────────────────────────────────────────────────────────────

class InputModal(ModalScreen[str | None]):
    """Single-line text input overlay."""

    BINDINGS = [Binding("escape", "cancel", show=False)]

    DEFAULT_CSS = """
    InputModal {
        align: center middle;
    }
    #im-box {
        background: #111111;
        border: tall #00d7ff;
        padding: 1 3;
        width: 68;
        height: auto;
    }
    #im-prompt {
        color: #555555;
        height: 1;
        margin-bottom: 1;
    }
    Input {
        background: #0a0a0a;
        border: tall #222222;
        color: #c9d1d9;
        height: 3;
    }
    Input:focus {
        border: tall #00d7ff;
    }
    #im-hint {
        color: #1e1e1e;
        text-align: right;
        height: 1;
        margin-top: 1;
    }
    """

    def __init__(self, prompt: str, placeholder: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Container(id="im-box"):
            yield Label(self._prompt, id="im-prompt")
            yield Input(placeholder=self._placeholder)
            yield Label("↵ confirm   esc cancel", id="im-hint")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ─── Project Screen ───────────────────────────────────────────────────────────

class ProjectScreen(Screen):
    """Full-screen project selector shown when cwd has no registered project."""

    BINDINGS = [Binding("q", "app.quit", show=False)]

    DEFAULT_CSS = """
    ProjectScreen {
        background: #0a0a0a;
        align: center middle;
    }
    #ps-wrap {
        width: 72;
        height: auto;
        padding: 2 3;
    }
    #ps-logo {
        color: #00d7ff;
        text-style: bold;
        text-align: center;
        height: 1;
    }
    #ps-sub {
        color: #1a1a1a;
        text-align: center;
        height: 1;
        margin-bottom: 2;
    }
    #ps-hdr {
        color: #2a2a2a;
        text-style: bold;
        height: 1;
    }
    #ps-rule {
        color: #141414;
        height: 1;
        margin-bottom: 1;
    }
    .ps-row {
        height: 1;
    }
    .ps-new {
        height: 1;
        margin-top: 1;
    }
    #ps-foot {
        color: #1a1a1a;
        text-align: right;
        height: 1;
        margin-top: 2;
    }
    """

    def __init__(self, projects: list) -> None:
        super().__init__()
        self._projects = projects

    def compose(self) -> ComposeResult:
        with Container(id="ps-wrap"):
            yield Static("M  A  G  N  A", id="ps-logo")
            yield Static("AI Context Engine", id="ps-sub")
            yield Static("SELECT PROJECT", id="ps-hdr")
            yield Static("─" * 62, id="ps-rule")
            for i, p in enumerate(self._projects):
                key = str(i + 1) if i < 9 else "0"
                yield Static(
                    f"  [cyan]{key}[/cyan]   {p.name:<26} [dim]{p.path}[/dim]",
                    markup=True, classes="ps-row",
                )
            yield Static(
                "  [dim]N[/dim]   Register new project...",
                markup=True, classes="ps-new",
            )
            yield Static("↵ number   n new   q quit", id="ps-foot")

    def on_key(self, event) -> None:
        key = event.key
        if key == "n":
            self._worker_new()
        elif key.isdigit():
            idx = (int(key) - 1) if key != "0" else 9
            if 0 <= idx < len(self._projects):
                p = self._projects[idx]
                os.chdir(p.path)
                self.app.switch_screen(MainScreen(p.name, p.path))

    @work
    async def _worker_new(self) -> None:
        path_str = await self.app.push_screen_wait(
            InputModal("Project root path", r"C:\Projects\my-project")
        )
        if not path_str:
            return
        target = Path(path_str.strip())
        if not target.exists():
            return
        os.chdir(target)
        self.app.switch_screen(MainScreen(target.name, str(target)))


# ─── Main Screen ──────────────────────────────────────────────────────────────

_MENU = [
    ("DOCUMENTATION", [
        ("1", "init",     "Map project architecture"),
        ("2", "project",  "Generate structural knowledge"),
        ("3", "file",     "Document a folder in depth"),
        ("4", "archive",  "Analyze a specific file"),
    ]),
    ("WORKFLOW", [
        ("5", "task",     "Launch Claude with task context"),
        ("6", "sync",     "Sync documentation post-task"),
        ("7", "resume",   "Resume reopened ticket"),
        ("8", "revision", "Resolve PR review criticals"),
    ]),
    ("EXPLORE", [
        ("9", "claude",   "Launch Claude with full context"),
        ("0", "status",   "View documented architecture"),
    ]),
]


class MainScreen(Screen):

    BINDINGS = [
        Binding("1", "cmd('init')",     show=False),
        Binding("2", "cmd('project')",  show=False),
        Binding("3", "cmd('file')",     show=False),
        Binding("4", "cmd('archive')",  show=False),
        Binding("5", "cmd('task')",     show=False),
        Binding("6", "cmd('sync')",     show=False),
        Binding("7", "cmd('resume')",   show=False),
        Binding("8", "cmd('revision')", show=False),
        Binding("9", "cmd('claude')",   show=False),
        Binding("0", "cmd('status')",   show=False),
        Binding("p", "change_proj",     show=False),
        Binding("q", "app.quit",        "Quit", show=True),
    ]

    DEFAULT_CSS = """
    MainScreen {
        background: #0a0a0a;
    }
    #logo {
        color: #00d7ff;
        text-style: bold;
        text-align: center;
        padding: 2 0 0 0;
        height: 2;
    }
    #tagline {
        color: #1a1a1a;
        text-align: center;
        height: 1;
        margin-bottom: 1;
    }
    #proj-bar {
        background: #0d0d0d;
        border-top: solid #181818;
        border-bottom: solid #181818;
        padding: 0 4;
        height: 4;
    }
    #proj-lbl {
        color: #252525;
        text-style: bold;
        width: 10;
        height: 4;
        content-align: left middle;
    }
    #proj-detail {
        height: 4;
        padding: 1 0;
    }
    #proj-name {
        color: #c9d1d9;
        text-style: bold;
        height: 1;
    }
    #proj-path {
        color: #252525;
        height: 1;
    }
    #menu {
        padding: 1 4;
    }
    .sec {
        color: #252525;
        text-style: bold;
        height: 1;
        margin-top: 1;
    }
    .rule {
        color: #141414;
        height: 1;
    }
    .item {
        height: 1;
    }
    .gap {
        height: 1;
    }
    #foot {
        color: #1a1a1a;
        text-align: right;
        padding: 0 4 1 0;
        height: 2;
        content-align: right bottom;
    }
    """

    def __init__(self, project_name: str, project_path: str) -> None:
        super().__init__()
        self._project_name = project_name
        self._project_path = project_path

    def compose(self) -> ComposeResult:
        yield Static("M  A  G  N  A", id="logo")
        yield Static("AI Context Engine", id="tagline")

        with Horizontal(id="proj-bar"):
            yield Label("PROJECT", id="proj-lbl")
            with Vertical(id="proj-detail"):
                yield Static(self._project_name, id="proj-name")
                yield Static(self._project_path, id="proj-path")

        with Container(id="menu"):
            for section, items in _MENU:
                yield Static(section, classes="sec")
                yield Static("─" * 56, classes="rule")
                for key, name, desc in items:
                    yield Static(
                        f"  [cyan]{key}[/cyan]   [bold]{name:<14}[/bold][dim]{desc}[/dim]",
                        markup=True, classes="item",
                    )
                yield Static("", classes="gap")

        yield Static("p change project   q quit", id="foot")

    def action_change_proj(self) -> None:
        self._worker_change()

    @work
    async def _worker_change(self) -> None:
        from sqlmodel import Session, select as sql_select
        from aicli.db import engine
        from aicli.db.models import Project
        with Session(engine) as session:
            projects = list(session.exec(sql_select(Project)).all())
        await self.app.push_screen(ProjectScreen(projects))

    def action_cmd(self, command: str) -> None:
        self._worker_cmd(command)

    @work
    async def _worker_cmd(self, command: str) -> None:  # noqa: C901
        if command == "init":
            with self.app.suspend():
                from aicli.commands.init import init
                init()

        elif command == "project":
            with self.app.suspend():
                from aicli.commands.proyecto import proyecto
                proyecto()

        elif command == "file":
            folder = await self.app.push_screen_wait(
                InputModal("Folder to document", "pagos  or  controllers/pagos")
            )
            if not folder:
                return
            with self.app.suspend():
                from aicli.commands.file_cmd import file_cmd
                file_cmd(folder)

        elif command == "archive":
            fp = await self.app.push_screen_wait(
                InputModal("File path", "pagos/PagosController.php")
            )
            if not fp:
                return
            with self.app.suspend():
                from aicli.commands.archive import archive
                archive(fp)

        elif command == "task":
            desc = await self.app.push_screen_wait(
                InputModal(
                    "Task description",
                    "Implement payment validation with zero amount...",
                )
            )
            if not desc:
                return
            fp = await self.app.push_screen_wait(
                InputModal("File path  (Enter to skip)", "pagos/PagosController.php")
            )
            with self.app.suspend():
                image = _ask_image()
                from aicli.commands.task import task
                task(desc, fp or None, image)

        elif command == "sync":
            with self.app.suspend():
                from aicli.commands.sync import sync
                sync()

        elif command == "resume":
            with self.app.suspend():
                _run_resume()

        elif command == "revision":
            with self.app.suspend():
                from aicli.commands.revision import revision
                revision()

        elif command == "claude":
            with self.app.suspend():
                from aicli.commands.claude_cmd import claude
                claude()

        elif command == "status":
            with self.app.suspend():
                from aicli.commands.status import status
                status()


def _run_resume() -> None:
    """Retomar flow — runs entirely in terminal inside suspend context."""
    import questionary
    from rich.console import Console
    from rich.panel import Panel as RichPanel
    from aicli.services.tickets import load_tickets, format_history, save_active_ticket
    from aicli.commands.task import _execute_task

    console = Console()
    style = _q_style()
    tickets = load_tickets()

    if tickets:
        choices = [
            questionary.Choice(f"  {tid}  ({len(d['rondas'])} ronda/s)", value=tid)
            for tid, d in tickets.items()
        ]
        choices.append(questionary.Choice("  Ingresar ID manualmente...", value="__manual__"))
        chosen = questionary.select("¿Qué ticket retomar?", choices=choices, style=style).ask()
    else:
        chosen = "__manual__"

    if chosen == "__manual__":
        chosen = questionary.text("  ID del ticket (ej: PROJ-1234)", style=style).ask()

    if not chosen or not chosen.strip():
        return

    ticket_id = chosen.strip().upper()
    history = format_history(ticket_id, tickets)
    if history:
        console.print()
        console.print(RichPanel(
            history,
            title=f"[bold cyan]Historial {ticket_id}[/bold cyan]",
            border_style="cyan",
        ))

    console.print()
    reason = questionary.text("  Motivo de reapertura", style=style).ask()
    if not reason or not reason.strip():
        return

    image = _ask_image()
    file_path = questionary.text(
        "  Archivo específico (Enter para omitir)", style=style
    ).ask()

    save_active_ticket(ticket_id, reason.strip())
    clean_file = file_path.strip() if file_path and file_path.strip() else None
    _execute_task(
        f"[TICKET REABIERTO {ticket_id}] {reason.strip()}",
        clean_file, image, ticket_history=history,
    )


# ─── Entry point ──────────────────────────────────────────────────────────────

class MagnaApp(App):
    CSS = "Screen { background: #0a0a0a; }"

    def on_mount(self) -> None:
        from sqlmodel import Session, select as sql_select
        from aicli.db import engine
        from aicli.db.models import Project

        current = str(Path.cwd())
        with Session(engine) as s:
            project = s.exec(
                sql_select(Project).where(Project.path == current)
            ).first()

        if project:
            self.push_screen(MainScreen(project.name, project.path))
            return

        with Session(engine) as s:
            projects = list(s.exec(sql_select(Project)).all())

        self.push_screen(ProjectScreen(projects))


def run_app() -> None:
    MagnaApp().run()
