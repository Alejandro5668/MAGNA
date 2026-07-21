from __future__ import annotations
import os
import logging
import traceback
from pathlib import Path

import pyfiglet
from rich.text import Text
from rich.panel import Panel as RichPanel
from textual.app import ComposeResult
from textual.screen import Screen, ModalScreen
from textual.widgets import (
    Static, Input, Label, DataTable,
    Footer, Rule, OptionList, Collapsible, RichLog, TextArea,
    ListView, ListItem,
)
from textual.widget import Widget
from textual.widgets.option_list import Option
from textual.containers import Container, Vertical, Horizontal
from textual.binding import Binding
from textual import work
from textual.message import Message
from textual.reactive import reactive

from .modals import (
    HelpScreen, InputModal, TextAreaModal, ConfirmModal, JiraCardModal,
)
from .widgets import TicketPanel

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


_ENV_LABELS: dict[str, str] = {
    "ANTHROPIC_API_KEY": "Anthropic API Key",
    "JIRA_URL":          "Jira URL",
    "JIRA_EMAIL":        "Jira Email",
    "JIRA_TOKEN":        "Jira Token",
    "GEMINI_API_KEY":    "Gemini API Key",
}


def _save_env_var(key: str, value: str) -> None:
    env_path = Path.home() / ".mycontext" / ".env"
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = [ln for ln in existing.splitlines() if ln.strip()]
    result, updated = [], False
    for line in lines:
        k = line.split("=", 1)[0] if "=" in line else ""
        if k == key:
            result.append(f"{key}={value}")
            updated = True
        else:
            result.append(line)
    if not updated:
        result.append(f"{key}={value}")
    env_path.write_text("\n".join(result) + "\n", encoding="utf-8")
    os.environ[key] = value


def _cfg_option(env_key: str) -> Option:
    label = _ENV_LABELS.get(env_key, env_key)
    is_set = bool(os.getenv(env_key))
    status = "✓ configurada" if is_set else "✗ no configurada"
    color  = _OK if is_set else _ERROR
    return Option(
        Text.assemble(
            ("  ", ""),
            (f"{label:<28}", "#F1F3F9"),
            (status, f"bold {color}"),
        ),
        id=f"k:{env_key}",
    )



def _error_panel(command: str, exc: BaseException, tb: str) -> RichPanel:
    """MAGNA-branded error panel for CommandOutputScreen."""
    body = Text()
    body.append(f"{type(exc).__name__}: ", style=f"bold {_ERROR}")
    body.append(str(exc), style=_ERROR)
    body.append(f"\n\n{tb}", style=_MUTED)
    body.append(f"\n  [esc] volver al dashboard   [0] ver logs completos", style=_SEC)
    return RichPanel(
        body,
        title=f"[bold {_ERROR}]✖  MAGNA — error en {command}[/bold {_ERROR}]",
        border_style=_ERROR,
        padding=(0, 1),
    )


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
    ("TEAM", [
        ("s", "settings", "Settings"),
    ]),
]


def _ask_image_tui(console) -> str | None:
    """Igual que _gather_image_async pero síncrono para llamadas desde thread."""
    use_cb = console.request_confirm("¿Tenés una captura en el portapapeles?", default=False)
    if not use_cb:
        return None
    captured = _capture_clipboard()
    if captured:
        console.print(f"[bold {_OK}]OK[/bold {_OK}] [{_SEC}]Guardada: {captured}[/{_SEC}]")
        return captured
    console.print(f"[{_WARN}]Sin imagen en el portapapeles.[/{_WARN}]")
    return None


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

    if not use_cb:
        return None
    captured = _capture_clipboard()
    if captured:
        console.print(f"  [bold {_OK}]OK[/bold {_OK}] [{_SEC}]Guardada: {captured}[/{_SEC}]")
        return captured
    console.print(f"  [{_WARN}]Sin imagen en el portapapeles.[/{_WARN}]")
    return None


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
                ticket_id=inputs.get("ticket_id"),
                jira_data=inputs.get("jira_data"),
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
        from pathlib import Path as _Path
        from sqlmodel import Session as _Session, select as _select
        from aicli.db import engine as _engine
        from aicli.db.models import Project as _Project, Module as _Module
        from aicli.services.builder import build_context as _build_ctx
        from aicli.services.caller import launch_claude as _launch
        from aicli.tui.theme import magna_warn as _mw, magna_error as _me

        path = _Path.cwd()
        with _Session(_engine) as s:
            project = s.exec(_select(_Project).where(_Project.path == str(path))).first()
        if not project:
            tui_console.print(f"[bold {_ERROR}]Proyecto no registrado. Ejecutá ctx init primero.[/bold {_ERROR}]")
            return
        with _Session(_engine) as s:
            modules = list(s.exec(_select(_Module).where(_Module.project_id == project.id)).all())
        if not modules:
            tui_console.print(f"[{_WARN}]Sin módulos documentados. Ejecutá ctx init primero.[/{_WARN}]")
            return

        tui_console.print(f"[{_SECTION}]Cargando contexto… {len(modules)} módulos[/{_SECTION}]")
        context, ctx_warnings = _build_ctx(modules, project_path=path)
        for w in ctx_warnings:
            tui_console.print(f"[{_WARN}]{w}[/{_WARN}]")

        tui_console.suspend_and_run(lambda: _launch(context, task=inputs["duda"], question_mode=True))


def _run_resume_tui(tui_console) -> None:
    """Flujo resume usando TuiConsole para output e InputModal para inputs."""
    from pathlib import Path as _Path
    from rich.panel import Panel as RichPanel
    from rich.text import Text as RichText
    from aicli.services.tickets import (
        load_tickets, format_history, save_active_ticket,
        get_ticket_branch, save_ticket_branch,
    )
    from aicli.services import git_utils
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

    # ── Branch checkout ───────────────────────────────────────────────────────
    cwd = _Path.cwd()
    saved_branch = get_ticket_branch(ticket_id)

    if saved_branch:
        ok, err = git_utils.checkout(saved_branch, cwd)
        if ok:
            tui_console.print(f"[{_OK}]✓ Branch: {saved_branch}[/{_OK}]")
        else:
            tui_console.print(f"[{_WARN}]No se pudo hacer checkout de '{saved_branch}': {err}[/{_WARN}]")
    else:
        matching = git_utils.branches_matching(ticket_id, cwd)
        recent   = [b for b in git_utils.recent_branches(cwd, 10) if b not in matching]
        candidates = matching + recent

        if candidates:
            lines = []
            for i, b in enumerate(candidates):
                star = f"[{_ACCENT}]★[/{_ACCENT}] " if b in matching else "  "
                lines.append(f"{star}{i + 1}. [{_SEC}]{b}[/{_SEC}]")
            tui_console.print(
                f"[{_SECTION}]Ramas disponibles (★ = matchea {ticket_id}):[/{_SECTION}]\n"
                + "\n".join(lines)
            )
            raw_b = tui_console.request_input("Número de rama (Enter para omitir)")

            branch = None
            if raw_b:
                if raw_b.strip().isdigit():
                    idx = int(raw_b.strip()) - 1
                    if 0 <= idx < len(candidates):
                        branch = candidates[idx]
                else:
                    branch = raw_b.strip()

            if branch:
                ok, err = git_utils.checkout(branch, cwd)
                if ok:
                    save_ticket_branch(ticket_id, branch)
                    tui_console.print(f"[{_OK}]✓ Branch: {branch}[/{_OK}]")
                else:
                    tui_console.print(f"[{_WARN}]checkout falló: {err}[/{_WARN}]")

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

    file_path = tui_console.request_input("Archivo específico (Enter para omitir)")
    save_active_ticket(ticket_id, reason)

    with _inject(task_mod, tui_console):
        task_mod._execute_task(
            f"[TICKET REABIERTO {ticket_id}] {reason}",
            file_path or None,
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

class StatusScreen(ModalScreen):

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("q",      "go_back", show=False),
    ]

    DEFAULT_CSS = f"""
    StatusScreen {{
        background: #000000;
    }}
    #st-frame {{
        width: 100%;
        height: 100%;
        background: #000000;
        layout: vertical;
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
    #st-body {{
        height: 1fr;
        overflow-y: auto;
    }}
    #st-table {{
        background: transparent;
        border: none;
        padding: 0 4;
        height: auto;
        color: {_SEC};
    }}
    #st-table .datatable--header {{
        background: transparent;
        color: {_MUTED};
        text-style: bold;
    }}
    #st-table .datatable--cursor {{
        background: {_SELECT};
        color: {_ACCENT};
        text-style: bold;
    }}
    #st-summary {{
        color: {_MUTED};
        padding: 0 4 0 4;
        height: 1;
    }}
    #st-foot {{
        dock: bottom;
        color: {_MUTED};
        text-align: right;
        padding: 0 2 0 2;
        height: 2;
        border-top: solid {_BORDER};
    }}
    Rule {{
        color: {_BORDER};
        margin: 0;
    }}
    """

    def __init__(self, project_name: str, project_path: str) -> None:
        super().__init__()
        self._project_name = project_name
        self._project_path = project_path

    def compose(self) -> ComposeResult:
        with Container(id="st-frame"):
            yield Static(_gradient_logo(), id="st-logo")
            yield Static("ARCHITECTURE", id="st-title")
            yield Static(self._project_name, id="st-proj")
            yield Rule(line_style="heavy")
            with Container(id="st-body"):
                yield DataTable(id="st-table", show_cursor=True, cursor_type="row")
                yield Static("", id="st-summary")
            yield Static(
                f"  [bold {_ACCENT}]esc[/bold {_ACCENT}] [{_SEC}]·[/{_SEC}] [{_SEC}]volver al dashboard[/{_SEC}]",
                id="st-foot", markup=True,
            )

    def on_mount(self) -> None:
        # Aplicar colores de la paleta MAGNA directamente — más confiable
        # que CSS cuando el DataTable component CSS tiene mayor especificidad
        table = self.query_one("#st-table", DataTable)
        table.styles.color = _SEC
        self._load()

    def _load(self) -> None:
        from datetime import datetime
        from rich.text import Text as RichText
        from sqlmodel import Session, select as sql_select
        from aicli.db import engine
        from aicli.db.models import Project, Module

        table = self.query_one(DataTable)
        # Columnas con color exacto de la paleta — ignora el CSS de Textual
        table.add_column(RichText("Folder",          style=f"bold {_MUTED}"), width=32)
        table.add_column(RichText("Modules",         style=f"bold {_MUTED}"), width=10)
        table.add_column(RichText("Last documented", style=f"bold {_MUTED}"))

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
            # Filas con color de la paleta directamente en el contenido
            table.add_row(
                RichText(f"{folder}/",    style=_SEC),
                RichText(str(len(mods)), style=_MUTED),
                RichText(date,           style=_MUTED),
            )

        total = len(modules)
        nf    = len(folders)
        self.query_one("#st-summary", Static).update(
            f"[{_MUTED}]{total} modules · {nf} folders[/{_MUTED}]"
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
        import concurrent.futures
        loop = asyncio.get_running_loop()

        try:
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
        except Exception as e:
            self.app.notify(f"Error al inicializar proyecto: {e}", severity="error", timeout=8)
            from sqlmodel import Session, select as _sel
            from aicli.db import engine
            from aicli.db.models import Project
            with Session(engine) as s:
                projects = list(s.exec(_sel(Project)).all())
            self.app.switch_screen(ProjectScreen(projects))


# ─── Project Screen ───────────────────────────────────────────────────────────

class ProjectScreen(Screen):

    BINDINGS = [Binding("q", "app.quit", show=False)]

    _cursor: reactive[int] = reactive(0, init=False)

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
    #ps-list {{
        height: auto;
        opacity: 0;
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

    def _total(self) -> int:
        return len(self._projects) + 1

    def _render_list(self) -> Text:
        t = Text()
        for i, p in enumerate(self._projects):
            key = str(i + 1) if i < 9 else "0"
            if i == self._cursor:
                t.append("▶ ", style=f"bold {_ACCENT}")
                t.append(f"{key}   ", style=f"bold {_ACCENT}")
                t.append(f"{p.name:<24}", style="bold #F1F3F9")
                t.append(f"  {p.path}", style=f"bold {_SEC}")
            else:
                t.append(f"  {key}   {p.name:<24}  {p.path}", style=_MUTED)
            t.append("\n")
        new_idx = len(self._projects)
        if new_idx == self._cursor:
            t.append("▶ N   ", style=f"bold {_ACCENT}")
            t.append("Register new project...", style="bold #F1F3F9")
        else:
            t.append("  N   Register new project...", style=_MUTED)
        return t

    def compose(self) -> ComposeResult:
        with Container(id="ps-wrap"):
            yield Static(_gradient_logo(), id="ps-logo")
            yield Static("AI Context Engine", id="ps-tagline")
            yield Static("SELECT PROJECT", id="ps-hdr")
            yield Rule()
            yield Static(self._render_list(), id="ps-list")
            yield Static(
                f"[bold {_ACCENT}]↑↓[/bold {_ACCENT}] [{_SEC}]navegar[/{_SEC}]"
                f"  [bold {_ACCENT}]↵[/bold {_ACCENT}] [{_SEC}]seleccionar[/{_SEC}]"
                f"  [bold {_ACCENT}]n[/bold {_ACCENT}] [{_SEC}]nuevo[/{_SEC}]"
                f"  [{_MUTED}]·[/{_MUTED}]"
                f"  [bold {_SEC}]q[/bold {_SEC}] [{_MUTED}]salir[/{_MUTED}]",
                id="ps-foot", markup=True,
            )

    def watch__cursor(self, value: int) -> None:
        self.query_one("#ps-list", Static).update(self._render_list())

    def on_mount(self) -> None:
        for sel in ("#ps-logo", "#ps-hdr", "#ps-list", "#ps-foot"):
            self.query_one(sel).styles.opacity = 0
        self.query_one(Rule).styles.opacity = 0
        self._animate_entry()

    def on_key(self, event) -> None:
        key = event.key
        total = self._total()
        if key in ("down", "j"):
            self._cursor = (self._cursor + 1) % total
        elif key in ("up", "k"):
            self._cursor = (self._cursor - 1) % total
        elif key == "enter":
            self._select_current()
        elif key == "n":
            self._worker_new()
        elif key.isdigit():
            idx = (int(key) - 1) if key != "0" else 9
            if 0 <= idx < len(self._projects):
                p = self._projects[idx]
                os.chdir(p.path)
                self.app.switch_screen(MainScreen(p.name, p.path))

    def _select_current(self) -> None:
        new_idx = len(self._projects)
        if self._cursor == new_idx:
            self._worker_new()
        elif 0 <= self._cursor < len(self._projects):
            p = self._projects[self._cursor]
            os.chdir(p.path)
            self.app.switch_screen(MainScreen(p.name, p.path))

    @work
    async def _animate_entry(self) -> None:
        import asyncio
        logo    = self.query_one("#ps-logo")
        tagline = self.query_one("#ps-tagline", Static)
        hdr     = self.query_one("#ps-hdr")
        rule    = self.query_one(Rule)
        ps_list = self.query_one("#ps-list")
        foot    = self.query_one("#ps-foot")

        logo.styles.animate("opacity", 1.0, duration=0.9, easing="in_out_cubic")

        await asyncio.sleep(0.55)
        tagline.update("")
        _FULL = "AI Context Engine"
        for i in range(len(_FULL) + 1):
            cursor = "▌" if i < len(_FULL) else ""
            tagline.update(_FULL[:i] + cursor)
            await asyncio.sleep(0.055)
        tagline.update(_FULL)

        await asyncio.sleep(0.1)
        for w in (hdr, rule, ps_list, foot):
            w.styles.animate("opacity", 1.0, duration=0.4, easing="in_out_cubic")

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


# ─── Log Screen ───────────────────────────────────────────────────────────────

class LogScreen(Screen):
    BINDINGS = [Binding("escape", "dismiss", show=False)]

    DEFAULT_CSS = f"""
    LogScreen {{
        layout: vertical;
        background: {_ELEVATED};
        padding: 1 2;
    }}
    #log-header {{
        height: 1;
        color: {_ACCENT};
        text-style: bold;
        margin-bottom: 1;
    }}
    #log-hint {{
        height: 1;
        color: {_MUTED};
        margin-top: 1;
    }}
    #log-view {{
        height: 1fr;
        border: solid {_BORDER_A};
        background: {_ELEVATED};
    }}
    """

    def compose(self) -> ComposeResult:
        log_path = Path.home() / ".mycontext" / "magna.log"
        content = (
            log_path.read_text(encoding="utf-8", errors="replace")
            if log_path.exists()
            else "(sin logs aún — los errores aparecerán aquí)"
        )
        yield Static(
            f"[bold {_ACCENT}]MAGNA — Logs[/bold {_ACCENT}]"
            f"  [{_MUTED}]{log_path}[/{_MUTED}]",
            id="log-header", markup=True,
        )
        yield TextArea(content, id="log-view", read_only=True)
        yield Static(
            f"  seleccioná con el mouse o teclado  ·  Ctrl+C para copiar  ·  [[esc]] volver",
            id="log-hint", markup=True,
        )

    def on_mount(self) -> None:
        ta = self.query_one("#log-view", TextArea)
        ta.move_cursor(ta.document.end)


# ─── Settings Screen ──────────────────────────────────────────────────────────

class SettingsScreen(Screen):

    BINDINGS = [
        Binding("escape", "app.pop_screen", show=False),
        Binding("q",      "app.pop_screen", show=False),
    ]

    DEFAULT_CSS = f"""
    SettingsScreen {{
        background: transparent;
    }}
    #cfg-logo {{
        text-align: center;
        padding: 1 0 0 0;
    }}
    #cfg-title {{
        color: {_SECTION};
        text-align: center;
        height: 1;
    }}
    #cfg-body {{
        height: 1fr;
        border-top: heavy {_BORDER_A};
        margin-top: 1;
        overflow-y: auto;
        padding: 0 6;
    }}
    .cfg-section-hdr {{
        color: {_SECTION};
        text-style: bold;
        height: 2;
        padding: 1 1 0 1;
    }}
    OptionList {{
        background: transparent;
        border: none;
        height: auto;
        padding: 0;
    }}
    OptionList > .option-list--option {{
        padding: 0 1;
    }}
    OptionList > .option-list--option-highlighted {{
        background: transparent;
    }}
    OptionList:focus > .option-list--option-highlighted {{
        background: {_SELECT};
    }}
    #cfg-foot {{
        dock: bottom;
        color: {_MUTED};
        text-align: center;
        height: 2;
        padding: 0 2;
        border-top: solid {_BORDER};
    }}
    Rule {{
        color: {_BORDER};
        margin: 0;
    }}
    """

    def _rule_options(self) -> list[Option]:
        rules_dir = Path.home() / ".mycontext" / "rules"
        rule_files = sorted(rules_dir.glob("*.md")) if rules_dir.exists() else []
        items = [
            Option(
                Text.assemble(("  ", ""), (f.name, _SEC), ("   ", ""), ("↵ eliminar", _MUTED)),
                id=f"rules:del:{f.name}",
            )
            for f in rule_files
        ]
        items.append(
            Option(Text.assemble(("  ", ""), ("+ Agregar regla...", _ACCENT)), id="rules:add")
        )
        return items

    def compose(self) -> ComposeResult:
        yield Static(_gradient_logo(), id="cfg-logo")
        yield Static("SETTINGS", id="cfg-title")
        with Container(id="cfg-body"):
            yield Static("  ▌  CREDENCIALES", classes="cfg-section-hdr")
            yield OptionList(
                _cfg_option("ANTHROPIC_API_KEY"),
                _cfg_option("JIRA_URL"),
                _cfg_option("JIRA_EMAIL"),
                _cfg_option("JIRA_TOKEN"),
                _cfg_option("GEMINI_API_KEY"),
                id="cfg-creds",
            )
            yield Rule()
            yield Static("  ▌  REGLAS DEL EQUIPO", classes="cfg-section-hdr")
            yield OptionList(*self._rule_options(), id="cfg-rules")
            yield Rule()
            yield Static("  ▌  LOGS", classes="cfg-section-hdr")
            yield OptionList(
                Option(
                    Text.assemble(("  ", ""), ("Ver magna.log", "#F1F3F9"), ("          →", _SEC)),
                    id="logs",
                ),
                id="cfg-logs",
            )
        yield Static(
            f"  [bold {_ACCENT}]↑↓[/bold {_ACCENT}] [{_SEC}]navegar[/{_SEC}]"
            f"  [bold {_ACCENT}]↵[/bold {_ACCENT}] [{_SEC}]editar · abrir[/{_SEC}]"
            f"  [bold {_ACCENT}]esc[/bold {_ACCENT}] [{_SEC}]volver[/{_SEC}]",
            id="cfg-foot", markup=True,
        )

    def on_mount(self) -> None:
        self.query_one("#cfg-creds", OptionList).focus()

    def _rebuild_creds(self) -> None:
        ol = self.query_one("#cfg-creds", OptionList)
        ol.clear_options()
        for key in _ENV_LABELS:
            ol.add_option(_cfg_option(key))

    def _rebuild_rules(self) -> None:
        ol = self.query_one("#cfg-rules", OptionList)
        ol.clear_options()
        for item in self._rule_options():
            ol.add_option(item)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._worker_action(event.option.id or "")

    @work
    async def _worker_action(self, opt_id: str) -> None:
        if opt_id.startswith("k:"):
            env_key = opt_id[2:]
            label   = _ENV_LABELS.get(env_key, env_key)
            hint    = "configurada — Enter para cambiar" if os.getenv(env_key) else "no configurada"
            value   = await self.app.push_screen_wait(InputModal(f"{label}  ({hint})", ""))
            if value and value.strip():
                _save_env_var(env_key, value.strip())
                self.app.notify(f"{label} guardada ✓", timeout=3)
                self._rebuild_creds()

        elif opt_id == "rules:add":
            file_path_str = await self.app.push_screen_wait(
                InputModal("Ruta del archivo de reglas (.md)", r"C:\rules\techlead-rules.md")
            )
            if not file_path_str:
                return
            src = Path(file_path_str.strip())
            if not src.exists() or src.suffix.lower() != ".md":
                self.app.notify(f"No encontrado o no es .md: {src}", severity="error", timeout=5)
                return
            rules_dir = Path.home() / ".mycontext" / "rules"
            rules_dir.mkdir(parents=True, exist_ok=True)
            (rules_dir / src.name).write_bytes(src.read_bytes())
            self.app.notify(f"Regla agregada: {src.name}", timeout=4)
            self._rebuild_rules()

        elif opt_id.startswith("rules:del:"):
            fname     = opt_id[10:]
            confirmed = await self.app.push_screen_wait(ConfirmModal(f"¿Eliminar {fname}?", default=False))
            if confirmed:
                dest = Path.home() / ".mycontext" / "rules" / fname
                if dest.exists():
                    dest.unlink()
                self.app.notify(f"Regla eliminada: {fname}", timeout=4)
                self._rebuild_rules()

        elif opt_id == "logs":
            await self.app.push_screen(LogScreen())


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
        Binding("s", "cmd('settings')",  show=False),
        Binding("g", "jump_top",         show=False),
        Binding("G", "jump_bottom",      show=False),
        Binding("h", "collapse_section", show=False),
        Binding("l", "expand_section",   show=False),
        Binding("t", "focus_tickets",    show=False),
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
            yield TicketPanel()
        yield Footer()

    # ── Event handlers ────────────────────────────────────────────────────────

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.action_cmd(event.option.id)

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_jump_top(self) -> None:
        focused = self.focused
        if isinstance(focused, OptionList) and focused.option_count > 0:
            focused.highlighted = 0
        elif isinstance(focused, ListView) and len(focused) > 0:
            focused.index = 0

    def action_jump_bottom(self) -> None:
        focused = self.focused
        if isinstance(focused, OptionList) and focused.option_count > 0:
            focused.highlighted = focused.option_count - 1
        elif isinstance(focused, ListView) and len(focused) > 0:
            focused.index = len(focused) - 1

    def action_focus_tickets(self) -> None:
        try:
            self.query_one("#tp-list", ListView).focus()
        except Exception:
            pass

    async def _offer_sync(self, out_screen, tui_console, loop) -> None:
        """Ofrece sync post-Claude. ticket_id pre-llenado via read_active_ticket()."""
        import concurrent.futures
        from rich.text import Text
        # call_from_thread no puede usarse desde el event loop — escribir directo al screen
        out_screen.write_line(Text.from_markup(f"\n[{_SECTION}]── Claude cerró ──[/{_SECTION}]"))
        do_sync = await self.app.push_screen_wait(
            ConfirmModal("¿Hacer sync ahora?", default=True)
        )
        if not do_sync:
            return
        out_screen.write_line(Text.from_markup(f"\n[{_ACCENT}]◆  Iniciando sync...[/{_ACCENT}]"))
        from aicli.tui.log_handler import tui_handler
        tui_handler.set_screen(out_screen)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                await loop.run_in_executor(pool, _dispatch_tui, "sync", {}, tui_console)
        except BaseException as e:
            tb = traceback.format_exc()
            logging.error("sync failed: %s", e, exc_info=True)
            out_screen.write_line(_error_panel("sync", e, tb))
        finally:
            tui_handler.clear_screen()

    def on_ticket_panel_ticket_selected(self, event: TicketPanel.TicketSelected) -> None:
        self._worker_task_from_ticket(event.ticket_id)

    @work
    async def _worker_task_from_ticket(self, ticket_id: str) -> None:
        import asyncio as _aio
        from aicli.tui.output_screen import CommandOutputScreen, TuiConsole
        from aicli.services.jira import is_configured, fetch_issue

        jira_data = None
        desc = ""
        tid = ticket_id.upper().strip()

        if is_configured():
            self.app.notify(f"Cargando {tid} de Jira…", timeout=15)
            try:
                jira_data = await _aio.get_running_loop().run_in_executor(None, fetch_issue, tid)
            except Exception:
                pass

        if jira_data:
            proceed = await self.app.push_screen_wait(JiraCardModal(jira_data))
            if not proceed:
                return
            desc = jira_data.get("description", "") or tid
        else:
            desc = await self.app.push_screen_wait(TextAreaModal("Descripción de la tarea"))
            if not desc:
                return

        fp = await self.app.push_screen_wait(
            InputModal("Archivo  (Enter para omitir)", "pagos/PagosController.php")
        )
        inputs = {
            "ticket_id": tid,
            "jira_data": jira_data,
            "desc": desc,
            "fp": fp or None,
            "image": None,
        }

        import asyncio, contextvars
        await self.app.push_screen_wait(CommandScreen("task", _cmd_desc("task")))
        out_screen = CommandOutputScreen("task", _cmd_desc("task"))
        out_screen._loop = asyncio.get_running_loop()
        out_screen._ctx  = contextvars.copy_context()
        self.app.push_screen(out_screen)
        await asyncio.sleep(0.05)
        tui_console = TuiConsole(out_screen)

        from aicli.tui.log_handler import tui_handler
        tui_handler.set_screen(out_screen)

        import concurrent.futures
        loop = asyncio.get_running_loop()
        _cmd_ok = True
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                await loop.run_in_executor(pool, _dispatch_tui, "task", inputs, tui_console)
        except BaseException as e:
            _cmd_ok = False
            tb = traceback.format_exc()
            logging.error("task (from ticket) failed: %s", e, exc_info=True)
            out_screen.write_line(_error_panel("task", e, tb))
        finally:
            tui_handler.clear_screen()

        if _cmd_ok:
            await self._offer_sync(out_screen, tui_console, loop)

        out_screen.mark_done()

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
        try:
            from sqlmodel import Session, select as sql_select
            from aicli.db import engine
            from aicli.db.models import Project
            with Session(engine) as session:
                projects = list(session.exec(sql_select(Project)).all())
            await self.app.push_screen(ProjectScreen(projects))
        except Exception as e:
            self.app.notify(f"No se pudo cargar proyectos: {e}", severity="error", timeout=6)

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

        if command == "settings":
            await self.app.push_screen(SettingsScreen())
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

        elif command == "claude":
            duda = await self.app.push_screen_wait(
                InputModal("¿Qué duda tenés?", "describe tu pregunta aquí")
            )
            if not duda or not duda.strip():
                return
            inputs["duda"] = duda.strip()

        elif command == "task":
            ticket_id = await self.app.push_screen_wait(
                InputModal("Ticket ID  (Enter para omitir)", "SOL-1234")
            )

            # ── Jira fetch + card de confirmación ────────────────────────────
            jira_data = None
            desc = ""

            if ticket_id:
                from aicli.services.jira import is_configured, fetch_issue, setup_credentials

                # Setup guiado (solo la primera vez)
                if not is_configured():
                    want_setup = await self.app.push_screen_wait(
                        ConfirmModal("¿Conectar Jira para auto-fetch de tickets?", default=False)
                    )
                    if want_setup:
                        jira_url = await self.app.push_screen_wait(
                            InputModal("Jira URL", "https://empresa.atlassian.net")
                        )
                        jira_email = await self.app.push_screen_wait(
                            InputModal("Email de Atlassian", "vos@empresa.com")
                        )
                        jira_token = await self.app.push_screen_wait(
                            InputModal("API Token  (id.atlassian.net → Security → API tokens)", "")
                        )
                        if jira_url and jira_email and jira_token:
                            setup_credentials(jira_url, jira_email, jira_token)
                            self.app.notify("Credenciales Jira guardadas ✓", timeout=3)

                if is_configured():
                    import asyncio as _aio
                    tid_clean = ticket_id.upper().strip()
                    self.app.notify(f"Cargando {tid_clean} de Jira…", timeout=15)
                    jira_data = await _aio.get_running_loop().run_in_executor(
                        None, fetch_issue, tid_clean
                    )

                if jira_data:
                    # Card con todo lo traído — usuario confirma o cancela
                    proceed = await self.app.push_screen_wait(JiraCardModal(jira_data))
                    if not proceed:
                        return
                    desc = jira_data.get("description", "") or ticket_id
                else:
                    self.app.notify("No se pudo cargar el ticket — ingresá descripción manual", severity="warning", timeout=4)
                    desc = await self.app.push_screen_wait(
                        TextAreaModal("Descripción de la tarea")
                    )
                    if not desc:
                        return
            else:
                # Sin ticket → descripción manual
                desc = await self.app.push_screen_wait(
                    TextAreaModal("Descripción de la tarea")
                )
                if not desc:
                    return

            # Única pregunta del flujo TUI
            fp = await self.app.push_screen_wait(
                InputModal("Archivo  (Enter para omitir)", "pagos/PagosController.php")
            )
            inputs["ticket_id"] = ticket_id.upper().strip() if ticket_id else None
            inputs["jira_data"] = jira_data
            inputs["desc"] = desc
            inputs["fp"] = fp or None
            inputs["image"] = None  # ponytail: imagen disponible por CLI --imagen, no en flujo TUI

        # ── Pantalla de transición ─────────────────────────────────────────────
        await self.app.push_screen_wait(CommandScreen(command, _cmd_desc(command)))

        # ── CommandOutputScreen — TUI sigue activa ─────────────────────────────
        import contextvars
        out_screen = CommandOutputScreen(command, _cmd_desc(command))
        out_screen._loop = asyncio.get_running_loop()
        out_screen._ctx  = contextvars.copy_context()  # preserva _active_app para modales en thread
        self.app.push_screen(out_screen)

        # Pequeño yield para que Textual monte la pantalla antes de arrancar
        await asyncio.sleep(0.05)

        tui_console = TuiConsole(out_screen)

        from aicli.tui.log_handler import tui_handler
        tui_handler.set_screen(out_screen)

        loop = asyncio.get_running_loop()
        _cmd_ok = True
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                await loop.run_in_executor(
                    pool, _dispatch_tui, command, inputs, tui_console
                )
        except BaseException as e:
            _cmd_ok = False
            tb = traceback.format_exc()
            logging.error("command %s failed: %s", command, e, exc_info=True)
            out_screen.write_line(_error_panel(command, e, tb))
        finally:
            tui_handler.clear_screen()

        if _cmd_ok and command in ("task", "resume"):
            await self._offer_sync(out_screen, tui_console, loop)

        out_screen.mark_done()
