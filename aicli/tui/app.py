from __future__ import annotations
import os
from pathlib import Path

import pyfiglet
from rich.text import Text
from textual.app import App, ComposeResult
from textual.screen import Screen, ModalScreen
from textual.widgets import (
    Static, Input, Label, DataTable, ListView, ListItem,
    Footer, Rule, Sparkline, TabbedContent, TabPane,
    OptionList, Collapsible, RichLog,
)
from textual.widgets.option_list import Option
from textual.containers import Container, Vertical, Horizontal
from textual.binding import Binding
from textual import work

# ─── Brand ────────────────────────────────────────────────────────────────────

_LOGO = pyfiglet.figlet_format("MAGNA", font="ansi_shadow").rstrip()


def _gradient_logo() -> Text:
    """MAGNA logo con gradiente vertical azul (#5B8DEF) → dorado (#FFB703)."""
    lines = _LOGO.split('\n')
    n = max(len(lines) - 1, 1)
    r0, g0, b0 = 91,  141, 239   # #5B8DEF
    r1, g1, b1 = 255, 183, 3     # #FFB703
    t = Text(no_wrap=True, overflow="crop")
    for i, line in enumerate(lines):
        ratio = i / n
        r = int(r0 + ratio * (r1 - r0))
        g = int(g0 + ratio * (g1 - g0))
        b = int(b0 + ratio * (b1 - b0))
        t.append(line + '\n', style=f'#{r:02x}{g:02x}{b:02x}')
    return t

# ─── Noche Estrellada — mirrors theme.py ──────────────────────────────────────
#
#  El negro (#000000) es el canvas de la terminal. NO se pinta.
#  Solo se pintan superficies explícitas.
#
_ACCENT   = "#FFB703"   # accent.primary
_SECTION  = "#5B8DEF"   # accent_secondary.info
_BORDER   = "#242C45"   # border.subtle
_BORDER_A = "#3A4468"   # border.active
_GLOW     = "#E8A20A"   # accent.hover
_ELEVATED = "#0D1120"   # surface.elevated  — único fondo pintado en paneles
_HOVER    = "#161d33"   # surface.hover
_SELECT   = "#4A3D1A"   # accent.selection_bg
_OK       = "#4ADE80"   # state.success
_WARN     = "#FBBF24"   # state.warning
_ERROR    = "#F87171"   # state.error
_MID      = "#3A4468"   # border.active (puntos separadores)
_SEC      = "#AAB4D4"   # text.secondary
_MUTED    = "#5E6A94"   # text.muted

_MENU = [
    ("DOCUMENTATION", [
        ("1", "file",     "Document folder"),
        ("2", "archive",  "Analyze file"),
    ]),
    ("WORKFLOW", [
        ("3", "task",     "Claude task context"),
        ("4", "sync",     "Sync docs post-task"),
        ("5", "resume",   "Resume ticket"),
    ]),
    ("EXPLORE", [
        ("6", "claude",   "Claude full context"),
        ("7", "status",   "View architecture"),
    ]),
]

_HELP_ROWS = [
    ("1 – 7",    "Ejecutar comando directamente"),
    ("j / ↓",    "Bajar en menú"),
    ("k / ↑",    "Subir en menú"),
    ("g",        "Saltar al primer ítem"),
    ("G",        "Saltar al último ítem"),
    ("h",        "Colapsar sección"),
    ("l",        "Expandir sección"),
    ("Enter",    "Seleccionar ítem del menú"),
    ("Tab",      "Cambiar pestaña del panel derecho"),
    ("p",        "Cambiar proyecto activo"),
    ("?",        "Esta ayuda"),
    ("Esc",      "Volver / Cancelar"),
    ("q",        "Salir"),
]



def _ask_image_tui(console) -> str | None:
    """Igual que _gather_image_async pero síncrono para llamadas desde thread."""
    use_cb = console.request_confirm("¿Tenés una captura en el portapapeles?", default=False)
    if use_cb:
        captured = _capture_clipboard()
        if captured:
            console.print(f"[bold {_OK}]OK[/bold {_OK}] [{_SEC}]Guardada: {captured}[/{_SEC}]")
            return captured
        console.print(f"[{_WARN}]Sin imagen en el portapapeles.[/{_WARN}]")
        return None
    manual = console.request_input("Ruta de imagen (Enter para omitir)")
    return manual or None


def _cmd_desc(command: str) -> str:
    for _, items in _MENU:
        for _, cmd, desc in items:
            if cmd == command:
                return desc
    return ""


_DESC_MAX = 22  # chars disponibles para descripción antes del wrap

def _menu_option(key: str, name: str, desc: str) -> Option:
    d = desc[:_DESC_MAX - 1] + "…" if len(desc) > _DESC_MAX else desc
    return Option(
        Text.assemble(
            ("  ", ""),
            (key, _ACCENT),
            ("  ", ""),
            (f"{name:<10}", f"bold #F1F3F9"),
            ("  ", ""),
            (d, _SEC),
        ),
        id=name,
    )


# ─── Terminal utilities (run inside suspend) ──────────────────────────────────

def _q_style():
    from questionary import Style
    from aicli.tui.theme import Q_STYLE_ARGS
    return Style(Q_STYLE_ARGS)


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
            console.print(f"  [bold {_OK}]OK[/bold {_OK}] [{_SEC}]Guardada: {captured}[/{_SEC}]")
            return captured
        console.print(f"  [{_WARN}]Sin imagen en el portapapeles.[/{_WARN}]")
        return None

    manual = questionary.text("  Ruta de imagen (Enter para omitir)", style=style).ask()
    return manual.strip() if manual and manual.strip() else None


def _run_resume() -> None:
    import questionary
    from rich.console import Console
    from rich.panel import Panel as RichPanel
    from aicli.services.tickets import load_tickets, format_history, save_active_ticket
    from aicli.commands.task import _execute_task
    from aicli.tui.theme import print_header

    console = Console()
    style = _q_style()
    print_header(console, "ctx resume", "Resume reopened ticket")

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
            title=f"[bold {_ACCENT}]Historial {ticket_id}[/bold {_ACCENT}]",
            border_style=_ACCENT,
        ))

    console.print()
    reason = questionary.text("  Motivo de reapertura", style=style).ask()
    if not reason or not reason.strip():
        return

    image = _ask_image()
    file_path = questionary.text("  Archivo específico (Enter para omitir)", style=style).ask()

    save_active_ticket(ticket_id, reason.strip())
    clean_file = file_path.strip() if file_path and file_path.strip() else None
    _execute_task(
        f"[TICKET REABIERTO {ticket_id}] {reason.strip()}",
        clean_file, image, ticket_history=history,
    )


def _dispatch_tui(command: str, inputs: dict, tui_console) -> None:
    """
    Versión TUI de dispatch: inyecta TuiConsole en cada módulo de comando
    para que el output aparezca en el RichLog de CommandOutputScreen.
    """
    from contextlib import contextmanager

    @contextmanager
    def _inject(mod, console):
        original = mod.console
        mod.console = console
        try:
            yield
        finally:
            mod.console = original

    if command == "init":
        import aicli.commands.init as mod
        with _inject(mod, tui_console):
            mod.init()

    elif command == "scan":
        import aicli.commands.proyecto as mod
        with _inject(mod, tui_console):
            mod.proyecto()

    elif command == "file":
        import aicli.commands.file_cmd as mod
        with _inject(mod, tui_console):
            mod.file_cmd(inputs["folder"])

    elif command == "archive":
        import aicli.commands.archive as mod
        with _inject(mod, tui_console):
            mod.archive(inputs["fp"])

    elif command == "task":
        import aicli.commands.task as mod
        with _inject(mod, tui_console):
            mod._execute_task(
                inputs["desc"],
                inputs.get("fp"),
                inputs.get("image"),
                suspend_fn=tui_console.suspend_and_run,
            )

    elif command == "sync":
        import aicli.commands.sync as mod
        with _inject(mod, tui_console):
            mod._sync_impl(
                ask_fn=lambda prompt, default="": tui_console.request_input(prompt, default or ""),
                confirm_fn=lambda prompt, default=True: tui_console.request_confirm(prompt, default),
            )

    elif command == "resume":
        _run_resume_tui(tui_console)

    elif command == "claude":
        import aicli.commands.claude_cmd as mod
        with _inject(mod, tui_console):
            tui_console.suspend_and_run(mod.claude)


def _run_resume_tui(tui_console) -> None:
    """Flujo resume usando TuiConsole para output e InputModal para inputs."""
    from rich.panel import Panel as RichPanel
    from rich.text import Text as RichText
    from aicli.services.tickets import load_tickets, format_history, save_active_ticket
    import aicli.commands.task as task_mod

    tickets = load_tickets()
    if tickets:
        choices = list(tickets.keys())
        items = "\n".join(f"  {i+1}. {tid}" for i, tid in enumerate(choices))
        tui_console.print(f"[{_SECTION}]Tickets disponibles:[/{_SECTION}]\n{items}")
        raw = tui_console.request_input("Número o ID del ticket")
        if not raw:
            return
        if raw.isdigit():
            idx = int(raw) - 1
            ticket_id = choices[idx].upper() if 0 <= idx < len(choices) else raw.upper()
        else:
            ticket_id = raw.upper()
    else:
        raw = tui_console.request_input("ID del ticket (ej: PROJ-1234)")
        if not raw:
            return
        ticket_id = raw.upper()

    history = format_history(ticket_id, tickets)
    if history:
        tui_console.print(RichPanel(
            history,
            title=f"[bold {_ACCENT}]Historial {ticket_id}[/bold {_ACCENT}]",
            border_style=_ACCENT,
        ))

    reason = tui_console.request_input("Motivo de reapertura")
    if not reason:
        return

    image = _ask_image_tui(tui_console)
    file_path = tui_console.request_input("Archivo específico (Enter para omitir)")
    save_active_ticket(ticket_id, reason)

    with _inject(task_mod, tui_console):
        task_mod._execute_task(
            f"[TICKET REABIERTO {ticket_id}] {reason}",
            file_path or None,
            image or None,
            ticket_history=history,
            suspend_fn=tui_console.suspend_and_run,
        )


def _inject(mod, console):
    """Context manager: reemplaza mod.console temporalmente."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        original = mod.console
        mod.console = console
        try:
            yield
        finally:
            mod.console = original

    return _ctx()


# ─── CSS compartido entre modales ─────────────────────────────────────────────
#  Los modales SÍ pintan fondo (superficie elevada sobre el canvas negro)

_MODAL_CSS = f"""
Rule {{
    color: {_BORDER};
    margin: 0 0 1 0;
}}
"""

# ─── Help Screen ──────────────────────────────────────────────────────────────

class HelpScreen(ModalScreen[None]):

    BINDINGS = [
        Binding("escape", "app.pop_screen", show=False),
        Binding("?",      "app.pop_screen", show=False),
        Binding("q",      "app.pop_screen", show=False),
    ]

    DEFAULT_CSS = f"""
    HelpScreen {{
        align: center middle;
    }}
    #help-box {{
        background: {_ELEVATED};
        border: double {_ACCENT};
        padding: 1 3;
        width: 58;
        height: auto;
    }}
    #help-title {{
        color: {_ACCENT};
        text-style: bold;
        text-align: center;
        height: 1;
        margin-bottom: 1;
    }}
    #help-content {{
        height: auto;
        background: transparent;
    }}
    #help-foot {{
        color: {_MUTED};
        text-align: right;
        height: 1;
        margin-top: 1;
    }}
    {_MODAL_CSS}
    """

    def compose(self) -> ComposeResult:
        with Container(id="help-box"):
            yield Static("━━━  KEYBINDINGS  ━━━", id="help-title")
            yield Rule()
            yield RichLog(markup=False, highlight=False, id="help-content")
            yield Rule()
            yield Static(f"[{_MUTED}][esc] cerrar[/{_MUTED}]", id="help-foot", markup=True)

    def on_mount(self) -> None:
        log = self.query_one("#help-content", RichLog)
        for key, desc in _HELP_ROWS:
            log.write(Text.assemble(
                ("  ", ""),
                (f"{key:<12}", _ACCENT),
                (desc, _SEC),
            ))


# ─── Input Modal ──────────────────────────────────────────────────────────────

class InputModal(ModalScreen[str | None]):

    BINDINGS = [Binding("escape", "cancel", show=False)]

    DEFAULT_CSS = f"""
    InputModal {{
        align: center middle;
    }}
    #im-box {{
        background: {_ELEVATED};
        border: double {_ACCENT};
        padding: 1 3;
        width: 68;
        height: auto;
    }}
    #im-header {{
        color: {_ACCENT};
        text-style: bold;
        text-align: center;
        height: 1;
        margin-bottom: 1;
    }}
    #im-prompt {{
        color: #F1F3F9;
        text-style: bold;
        height: 1;
        margin-bottom: 1;
    }}
    Input {{
        background: #000000;
        border: tall {_BORDER};
        color: #F1F3F9;
        height: 3;
    }}
    Input:focus {{
        border: tall {_ACCENT};
    }}
    #im-hint {{
        color: {_MUTED};
        text-align: right;
        height: 1;
        margin-top: 1;
    }}
    """

    def __init__(self, prompt: str, placeholder: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Container(id="im-box"):
            yield Static("━━━  MAGNA  ━━━", id="im-header")
            yield Label(self._prompt, id="im-prompt")
            yield Input(placeholder=self._placeholder)
            yield Label(f"[{_MUTED}][↵] confirm  [esc] cancel[/{_MUTED}]", id="im-hint", markup=True)

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ─── Confirm Modal ────────────────────────────────────────────────────────────

class ConfirmModal(ModalScreen[bool]):
    """Modal Yes/No nativo — reemplaza questionary.confirm en comandos TUI."""

    BINDINGS = [
        Binding("y",      "answer_yes", show=False),
        Binding("n",      "answer_no",  show=False),
        Binding("enter",  "answer_yes", show=False),
        Binding("escape", "answer_no",  show=False),
    ]

    DEFAULT_CSS = f"""
    ConfirmModal {{
        align: center middle;
    }}
    #cf-box {{
        background: {_ELEVATED};
        border: double {_ACCENT};
        padding: 1 3;
        width: 58;
        height: auto;
    }}
    #cf-header {{
        color: {_ACCENT};
        text-style: bold;
        text-align: center;
        height: 1;
        margin-bottom: 1;
    }}
    #cf-prompt {{
        color: #F1F3F9;
        text-style: bold;
        height: 1;
        margin-bottom: 1;
    }}
    #cf-hint {{
        color: {_MUTED};
        text-align: right;
        height: 1;
        margin-top: 1;
    }}
    """

    def __init__(self, prompt: str, default: bool = True) -> None:
        super().__init__()
        self._prompt = prompt
        self._default = default

    def compose(self) -> ComposeResult:
        hint = "[Y/n]" if self._default else "[y/N]"
        with Container(id="cf-box"):
            yield Static("━━━  MAGNA  ━━━", id="cf-header")
            yield Label(self._prompt, id="cf-prompt")
            yield Label(
                f"[{_MUTED}]{hint}  [y] sí  [n] no  [esc] cancelar[/{_MUTED}]",
                id="cf-hint", markup=True,
            )

    def action_answer_yes(self) -> None:
        self.dismiss(True)

    def action_answer_no(self) -> None:
        self.dismiss(False)


# ─── Command Transition Screen ────────────────────────────────────────────────

class CommandScreen(ModalScreen[None]):

    DEFAULT_CSS = f"""
    CommandScreen {{
        background: #000000;
    }}
    #cs-frame {{
        width: 100%;
        height: 100%;
        background: #000000;
        align: center middle;
    }}
    #cs-wrap {{
        width: 74;
        height: auto;
        background: #000000;
    }}
    #cs-logo {{
        color: {_ACCENT};
        text-align: center;
    }}
    #cs-cmd {{
        color: {_GLOW};
        text-style: bold;
        text-align: center;
        height: 1;
        margin-top: 1;
    }}
    #cs-desc {{
        color: {_SEC};
        text-align: center;
        height: 1;
    }}
    #cs-dots {{
        color: {_SECTION};
        text-align: center;
        height: 1;
        margin-top: 2;
    }}
    Rule {{
        color: {_BORDER};
        margin: 1 0;
    }}
    """

    def __init__(self, command: str, description: str) -> None:
        super().__init__()
        self._command = command
        self._description = description

    def compose(self) -> ComposeResult:
        with Container(id="cs-frame"):
            with Container(id="cs-wrap"):
                yield Static(_LOGO, markup=False, id="cs-logo")
                yield Rule(line_style="heavy")
                yield Static(f"ctx {self._command}", id="cs-cmd")
                yield Static(self._description, id="cs-desc")
                yield Static("◆  ◆  ◆", id="cs-dots")

    def on_mount(self) -> None:
        self._auto_dismiss()

    @work
    async def _auto_dismiss(self) -> None:
        import asyncio
        await asyncio.sleep(0.75)
        self.dismiss(None)


# ─── Status Screen ────────────────────────────────────────────────────────────

class StatusScreen(Screen):

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("q",      "go_back", show=False),
    ]

    DEFAULT_CSS = f"""
    StatusScreen {{
        background: transparent;
    }}
    #st-logo {{
        color: {_ACCENT};
        text-align: center;
        padding: 1 0 0 0;
    }}
    #st-title {{
        color: #F1F3F9;
        text-style: bold;
        text-align: center;
        height: 1;
        margin-top: 1;
    }}
    #st-proj {{
        color: {_SEC};
        text-align: center;
        height: 1;
        margin-bottom: 1;
    }}
    DataTable {{
        background: transparent;
        border: none;
        padding: 0 4;
        height: auto;
    }}
    DataTable > .datatable--header {{
        background: transparent;
        color: {_MUTED};
        text-style: bold;
    }}
    DataTable > .datatable--cursor {{
        background: {_SELECT};
        color: {_ACCENT};
    }}
    #st-summary {{
        color: {_SEC};
        padding: 1 4 0 4;
        height: 1;
    }}
    Rule {{
        color: {_BORDER};
        margin: 0;
    }}
    Footer {{
        background: transparent;
        border-top: solid {_BORDER};
    }}
    Footer > .footer--key {{
        color: {_ACCENT};
        background: transparent;
        text-style: bold;
    }}
    Footer > .footer--description {{
        color: {_MUTED};
    }}
    """

    def __init__(self, project_name: str, project_path: str) -> None:
        super().__init__()
        self._project_name = project_name
        self._project_path = project_path

    def compose(self) -> ComposeResult:
        yield Static(_LOGO, markup=False, id="st-logo")
        yield Static("ARCHITECTURE", id="st-title")
        yield Static(self._project_name, id="st-proj")
        yield Rule(line_style="heavy")
        yield DataTable(id="st-table", show_cursor=True)
        yield Static("", id="st-summary")
        yield Footer()

    def on_mount(self) -> None:
        self._load()

    def _load(self) -> None:
        from datetime import datetime
        from sqlmodel import Session, select as sql_select
        from aicli.db import engine
        from aicli.db.models import Project, Module

        table = self.query_one(DataTable)
        table.add_columns("Folder", "Modules", "Last documented")

        with Session(engine) as session:
            project = session.exec(
                sql_select(Project).where(Project.path == self._project_path)
            ).first()

        if not project:
            self.query_one("#st-summary", Static).update("No project registered in this directory.")
            return

        with Session(engine) as session:
            modules = list(
                session.exec(sql_select(Module).where(Module.project_id == project.id)).all()
            )

        if not modules:
            self.query_one("#st-summary", Static).update("No modules documented yet — run ctx init.")
            return

        folders: dict[str, list] = {}
        for m in modules:
            parts = Path(m.file_path).parts
            folder = parts[0] if len(parts) > 1 else "[root]"
            folders.setdefault(folder, []).append(m)

        def _last(mods: list) -> float:
            return max((m.last_updated_at or 0.0) for m in mods)

        for folder, mods in sorted(folders.items(), key=lambda x: _last(x[1]), reverse=True):
            ts = _last(mods)
            date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "—"
            table.add_row(f"{folder}/", str(len(mods)), date)

        self.query_one("#st-summary", Static).update(
            f"{len(modules)} modules · {len(folders)} folders"
        )

    def action_go_back(self) -> None:
        self.app.pop_screen()


# ─── Onboarding Screen ────────────────────────────────────────────────────────

class OnboardingScreen(Screen):

    DEFAULT_CSS = f"""
    OnboardingScreen {{
        background: transparent;
        align: center middle;
    }}
    #ob-wrap {{
        width: 70;
        height: auto;
        align: center middle;
    }}
    #ob-logo {{
        color: {_ACCENT};
        text-align: center;
        margin-bottom: 2;
    }}
    #ob-step {{
        color: {_MUTED};
        text-style: bold;
        text-align: center;
        height: 1;
    }}
    #ob-title {{
        color: #F1F3F9;
        text-style: bold;
        text-align: center;
        height: 1;
    }}
    #ob-desc {{
        color: {_SECTION};
        text-align: center;
        height: 1;
        margin-top: 1;
    }}
    #ob-note {{
        color: {_MUTED};
        text-align: center;
        height: 1;
        margin-top: 3;
    }}
    Rule {{
        color: {_BORDER};
        margin: 1 0;
    }}
    """

    def __init__(self, project_name: str, project_path: str) -> None:
        super().__init__()
        self._project_name = project_name
        self._project_path = project_path

    def compose(self) -> ComposeResult:
        with Container(id="ob-wrap"):
            yield Static(_LOGO, markup=False, id="ob-logo")
            yield Static("", id="ob-step")
            yield Rule()
            yield Static("", id="ob-title")
            yield Static("", id="ob-desc")
            yield Static("Esto se hace una sola vez.", id="ob-note")

    def _update(self, step: str, title: str, desc: str) -> None:
        self.query_one("#ob-step",  Static).update(step)
        self.query_one("#ob-title", Static).update(title)
        self.query_one("#ob-desc",  Static).update(desc)

    def on_mount(self) -> None:
        self._run()

    @work
    async def _run(self) -> None:
        import asyncio

        import asyncio
        import concurrent.futures
        loop = asyncio.get_running_loop()

        self._update("Paso 1 de 2", "Mapeando arquitectura",
                     "MAGNA analiza la estructura de tu proyecto con IA.")
        await asyncio.sleep(1.2)

        def _run_init():
            from aicli.commands.init import init
            init()

        with self.app.suspend():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                await loop.run_in_executor(pool, _run_init)

        self._update("Paso 2 de 2", "Detectando patrones",
                     "MAGNA documenta los módulos y patrones de código.")
        await asyncio.sleep(1.0)

        def _run_proyecto():
            from aicli.commands.proyecto import proyecto
            proyecto()

        with self.app.suspend():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                await loop.run_in_executor(pool, _run_proyecto)

        self.app.switch_screen(MainScreen(self._project_name, self._project_path))


# ─── Project Screen ───────────────────────────────────────────────────────────

class ProjectScreen(Screen):

    BINDINGS = [Binding("q", "app.quit", show=False)]

    DEFAULT_CSS = f"""
    ProjectScreen {{
        background: transparent;
        align: center middle;
    }}
    #ps-wrap {{
        width: 74;
        height: auto;
        padding: 1 2;
    }}
    #ps-logo {{
        text-align: center;
        margin-bottom: 1;
        opacity: 0;
    }}
    #ps-tagline {{
        color: {_SECTION};
        text-align: center;
        height: 1;
        margin-bottom: 1;
    }}
    #ps-hdr {{
        color: {_SEC};
        text-style: bold;
        height: 1;
        margin-top: 1;
        opacity: 0;
    }}
    Rule {{
        color: {_BORDER};
        margin: 0 0 1 0;
        opacity: 0;
    }}
    ListView {{
        height: auto;
        background: transparent;
        border: none;
        opacity: 0;
    }}
    ListItem {{
        background: transparent;
        height: 1;
        padding: 0 0;
    }}
    #ps-list ListItem.--highlight {{
        background: {_SELECT};
    }}
    #ps-list ListItem.--highlight > Label {{
        color: {_GLOW};
        text-style: bold;
    }}
    #ps-foot {{
        color: {_MUTED};
        text-align: center;
        height: 1;
        margin-top: 2;
        opacity: 0;
    }}
    """

    def __init__(self, projects: list) -> None:
        super().__init__()
        self._projects = projects

    def compose(self) -> ComposeResult:
        with Container(id="ps-wrap"):
            yield Static(_gradient_logo(), id="ps-logo")
            yield Static("AI Context Engine", id="ps-tagline")
            yield Static("SELECT PROJECT", id="ps-hdr")
            yield Rule()

            items: list[ListItem] = []
            for i, p in enumerate(self._projects):
                key = str(i + 1) if i < 9 else "0"
                items.append(ListItem(
                    Label(
                        f"  [{_ACCENT}]{key}[/{_ACCENT}]   [#F1F3F9]{p.name:<24}[/#F1F3F9]"
                        f"  [{_MUTED}]{p.path}[/{_MUTED}]",
                        markup=True,
                    ),
                    name=f"proj_{i}",
                ))
            items.append(ListItem(
                Label(f"  [{_MUTED}]N   Register new project...[/{_MUTED}]", markup=True),
                name="new",
            ))
            yield ListView(*items, id="ps-list")
            yield Static(
                f"[{_MUTED}]↑↓ navigate  ↵ select  n new  q quit[/{_MUTED}]",
                id="ps-foot", markup=True,
            )

    def on_mount(self) -> None:
        for sel in ("#ps-logo", "#ps-hdr", "#ps-list", "#ps-foot"):
            self.query_one(sel).styles.opacity = 0
        self.query_one(Rule).styles.opacity = 0
        self._animate_entry()

    @work
    async def _animate_entry(self) -> None:
        import asyncio
        logo    = self.query_one("#ps-logo")
        tagline = self.query_one("#ps-tagline", Static)
        hdr     = self.query_one("#ps-hdr")
        rule    = self.query_one(Rule)
        ps_list = self.query_one("#ps-list")
        foot    = self.query_one("#ps-foot")

        # ── 1. Logo fade in ───────────────────────────────────────────────────
        logo.styles.animate("opacity", 1.0, duration=0.9, easing="in_out_cubic")

        # ── 2. Tagline typing effect ──────────────────────────────────────────
        await asyncio.sleep(0.55)
        tagline.update("")
        _FULL = "AI Context Engine"
        for i in range(len(_FULL) + 1):
            cursor = "▌" if i < len(_FULL) else ""
            tagline.update(_FULL[:i] + cursor)
            await asyncio.sleep(0.055)
        tagline.update(_FULL)

        # ── 3. Rest aparece: header + rule + lista + footer fade-in ──────────
        await asyncio.sleep(0.1)
        for w in (hdr, rule, ps_list, foot):
            w.styles.animate("opacity", 1.0, duration=0.4, easing="in_out_cubic")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        name = event.item.name or ""
        if name == "new":
            self._worker_new()
        elif name.startswith("proj_"):
            idx = int(name.split("_")[1])
            if 0 <= idx < len(self._projects):
                p = self._projects[idx]
                os.chdir(p.path)
                self.app.switch_screen(MainScreen(p.name, p.path))

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
        self.app.switch_screen(OnboardingScreen(target.name, str(target)))


# ─── Main Screen ──────────────────────────────────────────────────────────────

class MainScreen(Screen):

    BINDINGS = [
        Binding("1", "cmd('file')",      show=False),
        Binding("2", "cmd('archive')",   show=False),
        Binding("3", "cmd('task')",      show=False),
        Binding("4", "cmd('sync')",      show=False),
        Binding("5", "cmd('resume')",    show=False),
        Binding("6", "cmd('claude')",    show=False),
        Binding("7", "cmd('status')",    show=False),
        Binding("g", "jump_top",         show=False),
        Binding("G", "jump_bottom",      show=False),
        Binding("h", "collapse_section", show=False),
        Binding("l", "expand_section",   show=False),
        Binding("p", "change_proj",      "Project"),
        Binding("q", "app.quit",         "Quit"),
        Binding("?", "help",             "Help"),
    ]

    DEFAULT_CSS = f"""
    MainScreen {{
        background: transparent;
    }}
    #logo {{
        text-align: center;
        padding: 1 0 0 0;
    }}
    #tagline {{
        color: {_SECTION};
        text-align: center;
        height: 1;
    }}
    #body {{
        height: 1fr;
        border-top: heavy {_BORDER_A};
        margin-top: 1;
    }}

    /* ── Panel izquierdo — puntillismo azul (hatch) ── */
    #left {{
        width: 54;
        hatch: "·" {_SECTION} 20%;
        border-right: solid {_BORDER};
        padding: 0 1;
        overflow-y: auto;
    }}
    #left:focus-within {{
        border-right: solid {_ACCENT};
    }}

    /* ── Collapsible — todo transparente, solo texto sobre negro ── */
    Collapsible {{
        background: transparent;
        border: none;
        margin: 0;
        padding: 0;
    }}
    CollapsibleTitle {{
        color: {_SECTION};
        background: transparent;
        text-style: bold;
        padding: 0 1;
        height: 2;
    }}
    CollapsibleTitle:focus {{
        color: {_ACCENT};
        background: transparent;
    }}
    CollapsibleTitle:hover {{
        color: {_ACCENT};
        background: transparent;
    }}
    Collapsible > Contents {{
        background: transparent;
        padding: 0;
        height: auto;
    }}

    /* ── OptionList ── */
    OptionList {{
        background: transparent;
        border: none;
        padding: 0;
        height: auto;
    }}
    OptionList > .option-list--option {{
        padding: 0 1;
        height: 1;
        color: #F1F3F9;
    }}
    OptionList > .option-list--option-highlighted {{
        background: transparent;
    }}
    OptionList:focus > .option-list--option-highlighted {{
        background: {_SELECT};
        color: {_GLOW};
    }}

    /* ── Panel derecho — tabs ── */
    #right-tabs {{
        width: 1fr;
        height: 1fr;
        border: none;
        padding: 0;
        background: transparent;
    }}
    #right-tabs:focus-within Tabs {{
        border-bottom: solid {_ACCENT};
    }}
    TabbedContent Tabs {{
        background: transparent;
        height: 3;
        border-bottom: solid {_BORDER};
    }}
    TabbedContent Tab {{
        background: transparent;
        color: {_MUTED};
        padding: 0 2;
    }}
    TabbedContent Tab.-active {{
        color: {_ACCENT};
        text-style: bold;
        background: transparent;
    }}
    TabbedContent Tab:hover {{
        background: transparent;
        color: {_SEC};
    }}
    ContentSwitcher {{
        background: transparent;
    }}
    TabbedContent TabPane {{
        padding: 1 2;
        background: transparent;
    }}

    /* ── RichLog ── */
    RichLog {{
        background: transparent;
        border: none;
        height: auto;
        max-height: 12;
        scrollbar-color: {_BORDER};
        scrollbar-color-hover: {_SECTION};
    }}

    /* ── Sparkline ── */
    Sparkline {{
        height: 4;
        margin: 1 0 0 0;
    }}
    Sparkline > .sparkline--max-color {{
        color: {_ACCENT};
    }}
    Sparkline > .sparkline--min-color {{
        color: {_BORDER};
    }}
    #spark-label {{
        color: {_MUTED};
        height: 1;
        margin-top: 1;
    }}

    /* ── Footer ── */
    Footer {{
        background: transparent;
        border-top: solid {_BORDER};
    }}
    Footer > .footer--key {{
        color: {_ACCENT};
        background: transparent;
        text-style: bold;
    }}
    Footer > .footer--description {{
        color: {_MUTED};
    }}

    /* ── Rule global ── */
    Rule {{
        color: {_BORDER};
        margin: 0;
    }}
    """

    def __init__(self, project_name: str, project_path: str) -> None:
        super().__init__()
        self._project_name = project_name
        self._project_path = project_path
        self._spark_phase: float = 0.0

    def compose(self) -> ComposeResult:
        yield Static(_gradient_logo(), id="logo")
        yield Static("AI Context Engine", id="tagline")
        with Horizontal(id="body"):
            with Vertical(id="left"):
                for section, items in _MENU:
                    with Collapsible(title=f"▌ {section}", collapsed=False, id=f"col-{section.lower()}"):
                        yield OptionList(
                            *[_menu_option(k, n, d) for k, n, d in items],
                            id=f"ol-{section.lower()}",
                        )
            with TabbedContent(id="right-tabs"):
                with TabPane("PROJECT", id="tab-project"):
                    yield RichLog(markup=False, highlight=False, id="log-project")
                with TabPane("SEMANA", id="tab-semana"):
                    yield RichLog(markup=False, highlight=False, id="log-semana")
                    yield Static("tareas · últimos 7 días", id="spark-label")
                    yield Sparkline([], summary_function=sum, id="spark")
                with TabPane("ACTIVITY", id="tab-activity"):
                    yield RichLog(markup=False, highlight=False, id="log-activity")
        yield Footer()

    def on_mount(self) -> None:
        self._fill_project()
        self._fill_semana()
        self._fill_activity()
        self.set_interval(0.25, self._animate_spark)

    def _animate_spark(self) -> None:
        import math
        self._spark_phase += 0.15
        p = self._spark_phase
        data = [
            abs(math.sin(p + i * 0.35)) * 3 + abs(math.sin(p * 1.3 + i * 0.6))
            for i in range(50)
        ]
        try:
            self.query_one("#spark", Sparkline).data = data
        except Exception:
            pass

    # ── Tab loaders ───────────────────────────────────────────────────────────

    def _fill_project(self) -> None:
        from pathlib import Path as _P
        from sqlmodel import Session, select as sql_select
        from aicli.db import engine
        from aicli.db.models import Project, Module

        log = self.query_one("#log-project", RichLog)
        log.clear()
        log.write(Text(self._project_name, style="bold #F1F3F9"))

        with Session(engine) as session:
            project = session.exec(
                sql_select(Project).where(Project.path == self._project_path)
            ).first()
            if project:
                modules = list(
                    session.exec(sql_select(Module).where(Module.project_id == project.id)).all()
                )
                folder_set = {
                    (_P(m.file_path).parts[0] if len(_P(m.file_path).parts) > 1 else "[root]")
                    for m in modules
                }
                log.write(Text.assemble(
                    (f"{len(modules)} módulos", _SEC),
                    ("  ·  ", _MID),
                    (f"{len(folder_set)} carpetas", _SEC),
                ))
                if project.stack:
                    log.write(Text(f"stack: {project.stack}", style=_MUTED))
            else:
                log.write(Text("Sin módulos documentados", style=_SEC))

    def _fill_semana(self) -> None:
        import time as _t
        from sqlmodel import Session, select as sql_select, col
        from aicli.db import engine
        from aicli.db.models import Activity

        log = self.query_one("#log-semana", RichLog)
        log.clear()

        with Session(engine) as session:
            week_ago = _t.time() - 7 * 86400
            week_acts = list(session.exec(
                sql_select(Activity)
                .where(Activity.timestamp > week_ago)
                .order_by(col(Activity.timestamp))
            ).all())

        task_evs = [a for a in week_acts if a.command == "task"]
        sync_evs = [a for a in week_acts if a.command == "sync"]

        now = _t.time()
        daily = [0] * 7
        for te in task_evs:
            days_ago = int((now - te.timestamp) / 86400)
            if 0 <= days_ago < 7:
                daily[6 - days_ago] += 1

        durations: list[float] = []
        for te in task_evs:
            ns = next((s for s in sync_evs if s.timestamp > te.timestamp), None)
            if ns:
                durations.append((ns.timestamp - te.timestamp) / 60)

        if durations:
            avg = sum(durations) / len(durations)
            avg_s = f"{avg / 60:.1f}h" if avg >= 60 else f"{int(avg)}min"
            log.write(Text.assemble(
                (f"{len(durations)} casos resueltos", _SEC),
                ("  ·  ", _MID),
                (avg_s, _ACCENT),
                (" promedio", _MUTED),
            ))
            if len(durations) > 1:
                best  = f"{int(min(durations))}min" if min(durations) < 60 else f"{min(durations)/60:.1f}h"
                worst = f"{int(max(durations))}min" if max(durations) < 60 else f"{max(durations)/60:.1f}h"
                log.write(Text(f"mejor {best}  ·  más largo {worst}", style=_SECTION))
        else:
            log.write(Text("Sin datos — usá ctx task + ctx sync", style=_SEC))

        self.query_one("#spark", Sparkline).data = daily

    def _fill_activity(self) -> None:
        import time as _t
        from sqlmodel import Session, select as sql_select, col
        from aicli.db import engine
        from aicli.db.models import Activity

        log = self.query_one("#log-activity", RichLog)
        log.clear()

        with Session(engine) as session:
            recent = list(session.exec(
                sql_select(Activity).order_by(col(Activity.timestamp).desc()).limit(8)
            ).all())

        if recent:
            for act in recent:
                rel  = self._rel(act.timestamp)
                desc_part = f"  {act.description[:28]}" if act.description else ""
                log.write(Text.assemble(
                    (f"ctx {act.command:<9}", _ACCENT),
                    (desc_part, _SEC),
                    (f"  {rel}", _MUTED),
                ))
        else:
            log.write(Text("Sin actividad registrada", style=_SEC))

    def _rel(self, ts: float) -> str:
        import time as _t
        delta = _t.time() - ts
        if delta < 3600:
            return f"hace {max(1, int(delta / 60))}min"
        if delta < 86400:
            return f"hace {int(delta / 3600)}h"
        return f"hace {int(delta / 86400)}d"

    # ── Event handlers ────────────────────────────────────────────────────────

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.action_cmd(event.option.id)

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_jump_top(self) -> None:
        if isinstance(self.focused, OptionList) and self.focused.option_count > 0:
            self.focused.highlighted = 0

    def action_jump_bottom(self) -> None:
        if isinstance(self.focused, OptionList) and self.focused.option_count > 0:
            self.focused.highlighted = self.focused.option_count - 1

    def action_collapse_section(self) -> None:
        self._set_focused_collapsible(True)

    def action_expand_section(self) -> None:
        self._set_focused_collapsible(False)

    def _set_focused_collapsible(self, collapsed: bool) -> None:
        node = self.focused
        while node is not None:
            if isinstance(node, Collapsible):
                node.collapsed = collapsed
                return
            node = node.parent

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())

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
        import asyncio
        import concurrent.futures
        from aicli.tui.output_screen import CommandOutputScreen, TuiConsole

        inputs: dict = {}

        if command == "status":
            await self.app.push_screen(
                StatusScreen(self._project_name, self._project_path)
            )
            return

        # ── Recoger inputs via InputModal (TUI, sin suspend) ──────────────────
        if command == "file":
            folder = await self.app.push_screen_wait(
                InputModal("Folder to document", "pagos  or  controllers/pagos")
            )
            if not folder:
                return
            inputs["folder"] = folder

        elif command == "archive":
            fp = await self.app.push_screen_wait(
                InputModal("File path", "pagos/PagosController.php")
            )
            if not fp:
                return
            inputs["fp"] = fp

        elif command == "task":
            desc = await self.app.push_screen_wait(
                InputModal("Task description", "Implement payment validation...")
            )
            if not desc:
                return
            fp = await self.app.push_screen_wait(
                InputModal("File path  (Enter to skip)", "pagos/PagosController.php")
            )
            inputs["desc"] = desc
            inputs["fp"] = fp or None

        # ── Pantalla de transición ─────────────────────────────────────────────
        await self.app.push_screen_wait(CommandScreen(command, _cmd_desc(command)))

        # ── CommandOutputScreen — TUI sigue activa ─────────────────────────────
        out_screen = CommandOutputScreen(command, _cmd_desc(command))
        out_screen._loop = asyncio.get_running_loop()
        self.app.push_screen(out_screen)

        # Pequeño yield para que Textual monte la pantalla antes de arrancar
        await asyncio.sleep(0.05)

        tui_console = TuiConsole(out_screen)

        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            await loop.run_in_executor(
                pool, _dispatch_tui, command, inputs, tui_console
            )

        out_screen.mark_done()


# ─── App entry point ──────────────────────────────────────────────────────────

class MagnaApp(App):
    # Canvas negro — no se pinta; la terminal del usuario es el fondo
    CSS = "Screen { background: transparent; }"

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
