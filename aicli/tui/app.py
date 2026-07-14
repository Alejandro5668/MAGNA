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
    OptionList, Collapsible, RichLog, TextArea,
)
from textual.widgets.option_list import Option
from textual.containers import Container, Vertical, Horizontal
from textual.binding import Binding
from textual import work
from textual.reactive import reactive

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
            yield Static(
                f"[bold {_ACCENT}][esc][/bold {_ACCENT}] [{_SEC}]cerrar[/{_SEC}]",
                id="help-foot", markup=True,
            )

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
            yield Label(
                f"[bold {_ACCENT}][↵][/bold {_ACCENT}] [{_SEC}]confirmar[/{_SEC}]"
                f"  [{_MUTED}]·[/{_MUTED}]  [bold {_ERROR}][esc][/bold {_ERROR}] [{_SEC}]cancelar[/{_SEC}]",
                id="im-hint", markup=True,
            )

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ─── TextArea Modal ───────────────────────────────────────────────────────────

class TextAreaModal(ModalScreen[str | None]):
    """Modal multilinea para descripciones de tarea. Ctrl+Enter o Ctrl+S confirma."""

    BINDINGS = [
        Binding("escape", "cancel", show=False),
    ]

    DEFAULT_CSS = f"""
    TextAreaModal {{
        align: center middle;
    }}
    #tam-box {{
        background: {_ELEVATED};
        border: double {_ACCENT};
        padding: 1 3;
        width: 82;
        height: auto;
    }}
    #tam-header {{
        color: {_ACCENT};
        text-style: bold;
        text-align: center;
        height: 1;
        margin-bottom: 1;
    }}
    #tam-prompt {{
        color: #F1F3F9;
        text-style: bold;
        height: 1;
        margin-bottom: 1;
    }}
    #tam-subtitle {{
        color: {_SECTION};
        height: 1;
        margin-bottom: 1;
    }}
    TextArea {{
        background: #000000;
        border: tall {_BORDER};
        color: #F1F3F9;
        height: 8;
        scrollbar-color: {_BORDER};
    }}
    TextArea:focus {{
        border: tall {_ACCENT};
    }}
    #tam-hint {{
        color: {_MUTED};
        text-align: right;
        height: 1;
        margin-top: 1;
    }}
    {_MODAL_CSS}
    """

    def __init__(self, prompt: str, initial_text: str = "", subtitle: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._initial_text = initial_text
        self._subtitle = subtitle

    def compose(self) -> ComposeResult:
        with Container(id="tam-box"):
            yield Static("━━━  MAGNA  ━━━", id="tam-header")
            yield Label(self._prompt, id="tam-prompt")
            if self._subtitle:
                yield Label(self._subtitle, id="tam-subtitle", markup=True)
            yield TextArea(show_line_numbers=False)
            yield Label(
                f"[bold {_ACCENT}][ctrl+↵][/bold {_ACCENT}] [{_SEC}]confirmar[/{_SEC}]"
                f"  [bold {_ACCENT}][ctrl+s][/bold {_ACCENT}] [{_SEC}]también[/{_SEC}]"
                f"  [{_MUTED}]·[/{_MUTED}]  [bold {_ERROR}][esc][/bold {_ERROR}] [{_SEC}]cancelar[/{_SEC}]",
                id="tam-hint", markup=True,
            )

    def on_mount(self) -> None:
        ta = self.query_one(TextArea)
        ta.focus()
        if self._initial_text:
            ta.load_text(self._initial_text)

    def on_key(self, event) -> None:
        if event.key in ("ctrl+enter", "ctrl+s"):
            event.stop()
            self.action_submit()

    def action_submit(self) -> None:
        text = self.query_one(TextArea).text.strip()
        self.dismiss(text or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ─── Confirm Modal ────────────────────────────────────────────────────────────

class ConfirmModal(ModalScreen[bool]):
    """Modal Yes/No nativo — reemplaza questionary.confirm en comandos TUI."""

    BINDINGS = [
        Binding("y",      "answer_yes", show=False),
        Binding("n",      "answer_no",  show=False),
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
        enter_label = "↵ sí" if self._default else "↵ no"
        with Container(id="cf-box"):
            yield Static("━━━  MAGNA  ━━━", id="cf-header")
            yield Label(self._prompt, id="cf-prompt")
            yield Label(
                f"[bold {_OK}][y][/bold {_OK}] [{_SEC}]sí[/{_SEC}]"
                f"  [bold {_ERROR}][n][/bold {_ERROR}] [{_SEC}]no[/{_SEC}]"
                f"  [{_MUTED}]·[/{_MUTED}]"
                f"  [bold {_ACCENT}][↵][/bold {_ACCENT}] [{_SEC}]{enter_label}[/{_SEC}]"
                f"  [{_MUTED}]·[/{_MUTED}]  [bold {_ERROR}][esc][/bold {_ERROR}] [{_SEC}]cancelar[/{_SEC}]",
                id="cf-hint", markup=True,
            )

    def on_key(self, event) -> None:
        if event.key == "enter":
            event.stop()
            self.dismiss(self._default)

    def action_answer_yes(self) -> None:
        self.dismiss(True)

    def action_answer_no(self) -> None:
        self.dismiss(False)


# ─── Jira Card Modal ──────────────────────────────────────────────────────────

class JiraCardModal(ModalScreen[bool]):
    """Card de solo lectura con lo que se trajo de Jira. Enter=continuar, Esc=cancelar."""

    BINDINGS = [
        Binding("enter",  "proceed", show=False),
        Binding("escape", "cancel",  show=False),
    ]

    _IMG_MIME = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
    _XLS_MIME = frozenset({
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    })

    DEFAULT_CSS = f"""
    JiraCardModal {{
        align: center middle;
    }}
    #jc-box {{
        background: {_ELEVATED};
        border: double {_ACCENT};
        padding: 1 3;
        width: 76;
        height: auto;
    }}
    #jc-header {{
        color: {_ACCENT};
        text-style: bold;
        text-align: center;
        height: 1;
        margin-bottom: 1;
    }}
    #jc-badges {{
        height: 1;
        margin-bottom: 1;
    }}
    #jc-people {{
        height: 1;
        margin-bottom: 1;
    }}
    #jc-summary {{
        color: #F1F3F9;
        text-style: bold;
        height: auto;
        margin-bottom: 1;
    }}
    #jc-desc-label {{
        height: 1;
    }}
    #jc-desc {{
        color: {_SEC};
        height: auto;
    }}
    #jc-truncated {{
        height: 1;
        margin-bottom: 1;
    }}
    #jc-atts-label {{
        height: 1;
    }}
    #jc-atts {{
        height: auto;
        margin-bottom: 1;
    }}
    #jc-hint {{
        text-align: center;
        height: 1;
        margin-top: 1;
    }}
    {_MODAL_CSS}
    """

    def __init__(self, data: dict) -> None:
        super().__init__()
        self._d = data

    def _att_markup(self, att: dict) -> str:
        mime = att.get("mimeType", "")
        name = att.get("filename", "adjunto")
        if mime in self._IMG_MIME:
            tag, color = "IMG", _OK
        elif mime in self._XLS_MIME:
            tag, color = "XLS", _WARN
        else:
            tag, color = "ATT", _SECTION
        return f"[bold {color}][{tag}][/bold {color}] [{_SEC}]{name}[/{_SEC}]"

    def compose(self) -> ComposeResult:
        d = self._d
        atts = d.get("attachments", []) or []
        status   = d.get("status",   "")
        priority = d.get("priority", "")
        assignee = d.get("assignee", "")
        reporter = d.get("reporter", "")

        desc_raw  = (d.get("description", "") or "").strip()
        truncated = len(desc_raw) > 600
        desc_text = (desc_raw[:600] if truncated else desc_raw).replace("\n\n", "\n") or "(sin descripción)"

        with Container(id="jc-box"):
            yield Static("━━━  MAGNA  ━━━", id="jc-header")

            # ID · estado · prioridad
            badge = f"[bold {_ACCENT}]{d['id']}[/bold {_ACCENT}]"
            if status:
                badge += f"  [{_MUTED}]│[/{_MUTED}]  [{_SEC}]{status}[/{_SEC}]"
            if priority:
                badge += f"  [{_MUTED}]│[/{_MUTED}]  [{_WARN}]{priority}[/{_WARN}]"
            yield Label(badge, id="jc-badges", markup=True)

            # Asignado · Reportado
            people = []
            if assignee:
                people.append(f"Asignado a: {assignee}")
            if reporter:
                people.append(f"Reportado por: {reporter}")
            if people:
                yield Label(
                    f"[{_MUTED}]{' · '.join(people)}[/{_MUTED}]",
                    id="jc-people", markup=True,
                )

            yield Label(d.get("summary", ""), id="jc-summary")
            yield Rule()

            yield Label(
                f"[bold {_SECTION}]Descripción[/bold {_SECTION}]",
                id="jc-desc-label", markup=True,
            )
            yield Label(desc_text, id="jc-desc")
            if truncated:
                yield Label(
                    f"[{_MUTED}](… continúa en Claude)[/{_MUTED}]",
                    id="jc-truncated", markup=True,
                )

            if atts:
                yield Rule()
                yield Label(
                    f"[bold {_SECTION}]Adjuntos[/bold {_SECTION}]",
                    id="jc-atts-label", markup=True,
                )
                with Vertical(id="jc-atts"):
                    for att in atts:
                        yield Label(self._att_markup(att), markup=True)

            yield Rule()
            yield Label(
                f"[bold {_ACCENT}][↵][/bold {_ACCENT}] [{_SEC}]continuar[/{_SEC}]"
                f"  [{_MUTED}]·[/{_MUTED}]  "
                f"[bold {_ERROR}][esc][/bold {_ERROR}] [{_SEC}]cancelar[/{_SEC}]",
                id="jc-hint", markup=True,
            )

    def action_proceed(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
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
        max-height: 20;
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
                with TabPane("VELOCIDAD", id="tab-velocidad"):
                    yield RichLog(markup=False, highlight=False, id="log-velocidad")
                    yield Static("casos / día · últimos 7 días", id="spark-label", markup=True)
                    yield Sparkline([], summary_function=sum, id="spark")
                with TabPane("CALIDAD", id="tab-calidad"):
                    yield RichLog(markup=False, highlight=False, id="log-calidad")
                with TabPane("AHORA", id="tab-ahora"):
                    yield RichLog(markup=False, highlight=False, id="log-ahora")
        yield Footer()

    def on_mount(self) -> None:
        self._fill_velocidad()
        self._fill_calidad()
        self._fill_ahora()

    # ── Tab loaders ───────────────────────────────────────────────────────────

    def _fill_velocidad(self) -> None:
        import time as _t
        from sqlmodel import Session, select as sql_select, col
        from aicli.db import engine
        from aicli.db.models import Activity

        log = self.query_one("#log-velocidad", RichLog)
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
            avg   = sum(durations) / len(durations)
            best  = min(durations)
            worst = max(durations)

            def _fmt(m: float) -> str:
                return f"{m / 60:.1f}h" if m >= 60 else f"{int(m)}min"

            log.write(Text.assemble(("Tiempo promedio / caso   ", _MUTED), (_fmt(avg),   _ACCENT)))
            log.write(Text.assemble(("Mejor caso esta semana   ", _MUTED), (_fmt(best),  _OK)))
            log.write(Text.assemble(("Caso más largo           ", _MUTED), (_fmt(worst), _ERROR)))
            log.write(Text(" "))

            fast   = sum(1 for d in durations if d < 30)
            normal = sum(1 for d in durations if 30 <= d <= 120)
            slow   = sum(1 for d in durations if d > 120)
            total  = len(durations)
            MAX_B  = 8

            def _bar(n: int) -> str:
                filled = round(n / total * MAX_B) if total else 0
                return "█" * filled + "░" * (MAX_B - filled)

            log.write(Text(f"Distribución  {total} casos", style=f"bold {_SEC}"))
            log.write(Text.assemble(("  Rápido  < 30min  ", _MUTED), (_bar(fast),   _OK),    (f"  {fast}", _SEC)))
            log.write(Text.assemble(("  Normal  30–120m  ", _MUTED), (_bar(normal), _ACCENT), (f"  {normal}", _SEC)))
            log.write(Text.assemble(("  Largo   > 2h     ", _MUTED), (_bar(slow),   _ERROR),  (f"  {slow}", _SEC)))
        else:
            log.write(Text("Sin datos — usá ctx task + ctx sync", style=_SEC))

        self.query_one("#spark", Sparkline).data = daily

    def _fill_calidad(self) -> None:
        import json
        from pathlib import Path as _P
        from collections import Counter

        log = self.query_one("#log-calidad", RichLog)
        log.clear()

        tickets_path = _P.home() / ".mycontext" / "tickets.json"
        if not tickets_path.exists():
            log.write(Text("Sin historial — usá ctx sync para registrar casos", style=_SEC))
            return

        try:
            raw: dict = json.loads(tickets_path.read_text(encoding="utf-8"))
        except Exception:
            log.write(Text("Error leyendo historial de tickets", style=_MUTED))
            return

        if not raw:
            log.write(Text("Sin historial — usá ctx sync para registrar casos", style=_SEC))
            return

        total        = len(raw)
        reabiertos   = sum(1 for d in raw.values() if len(d["rondas"]) > 1)
        total_rondas = sum(len(d["rondas"]) for d in raw.values())
        avg_rondas   = total_rondas / total if total else 0
        reopen_pct   = reabiertos / total * 100 if total else 0

        rate_color = _OK if reopen_pct < 15 else (_WARN if reopen_pct < 30 else _ERROR)
        warn_sym   = " ⚠" if reopen_pct >= 15 else ""

        log.write(Text.assemble(("Tickets resueltos    ", _MUTED), (str(total), _SEC)))
        log.write(Text.assemble(("Reabiertos por QA    ", _MUTED), (f"{reabiertos}  ({reopen_pct:.0f}%){warn_sym}", rate_color)))
        log.write(Text.assemble(("Promedio rondas      ", _MUTED), (f"{avg_rondas:.1f}", _SEC)))
        log.write(Text(" "))

        file_counts: Counter = Counter()
        for data in raw.values():
            if len(data["rondas"]) > 1:
                for ronda in data["rondas"][1:]:
                    for f in ronda.get("archivos_tocados", []):
                        file_counts[f] += 1

        if file_counts:
            log.write(Text("Archivos más reabiertos", style=f"bold {_SEC}"))
            for fpath, cnt in file_counts.most_common(3):
                short = (fpath.split("/")[-1] if "/" in fpath else fpath)[:26]
                log.write(Text.assemble(("  ", ""), (f"{short:<26}", _SEC), (f" ×{cnt}", _WARN)))
            log.write(Text(" "))

        motivos = [
            r["motivo_reapertura"]
            for d in raw.values()
            for r in d["rondas"]
            if r.get("motivo_reapertura")
        ]
        if motivos:
            log.write(Text("Motivos frecuentes", style=f"bold {_SEC}"))
            seen: list[str] = []
            for m in reversed(motivos):
                s = m[:42]
                if s not in seen:
                    seen.append(s)
                if len(seen) >= 3:
                    break
            for m in seen:
                log.write(Text(f"  · {m}", style=_MUTED))

    def _fill_ahora(self) -> None:
        from pathlib import Path as _P
        from sqlmodel import Session, select as sql_select, col
        from aicli.db import engine
        from aicli.db.models import Activity, Project, Module
        from aicli.services.tickets import read_active_ticket, load_tickets

        log = self.query_one("#log-ahora", RichLog)
        log.clear()

        # ── Aviso de session contexts expirados ───────────────────────────────
        notice_path = _P.home() / ".mycontext" / ".session_purge_notice"
        if notice_path.exists():
            try:
                count = int(notice_path.read_text(encoding="utf-8").strip())
                notice_path.unlink()
                s = "s" if count > 1 else ""
                log.write(Text.assemble(
                    ("⚠  ", f"bold {_WARN}"),
                    (f"{count} session context{s} eliminado{s} (>4h)", f"bold {_WARN}"),
                ))
                log.write(Text.assemble(
                    ("   ", ""),
                    ("Si Claude sigue abierto para ese ticket,", _SEC),
                ))
                log.write(Text.assemble(
                    ("   ", ""),
                    ("relanzá ctx task para regenerar el contexto.", _SEC),
                ))
                log.write(Text(" "))
            except Exception:
                pass

        # ── Proyecto ───────────────────────────────────────────────────────────
        with Session(engine) as session:
            project = session.exec(
                sql_select(Project).where(Project.path == self._project_path)
            ).first()
            mod_count = 0
            stack = "?"
            if project:
                mod_count = len(list(session.exec(
                    sql_select(Module).where(Module.project_id == project.id)
                ).all()))
                stack = project.stack or "?"

        log.write(Text.assemble(
            (f"{self._project_name:<22}", "bold #F1F3F9"),
            (stack, _SECTION),
            ("  ·  ", _MUTED),
            (f"{mod_count} módulos", _MUTED),
        ))
        log.write(Text(" "))

        # ── Ticket activo ──────────────────────────────────────────────────────
        active = read_active_ticket()
        if active:
            tid      = active.get("ticket_id", "")
            motivo   = active.get("motivo_reapertura", "")
            tickets  = load_tickets()
            n_rondas = len(tickets.get(tid, {}).get("rondas", [])) + 1
            desc     = tickets.get(tid, {}).get("descripcion", "")
            log.write(Text.assemble(
                ("◆ ", _ACCENT),
                (tid, f"bold {_ACCENT}"),
                ("  ", ""),
                (desc[:30] if desc else "", _SEC),
            ))
            log.write(Text.assemble(
                ("  Ronda ", _MUTED), (str(n_rondas), _SEC),
                ("  ·  ", _MUTED),   ((motivo[:30] if motivo else ""), _MUTED),
            ))
        else:
            log.write(Text("Sin ticket activo", style=_MUTED))

        log.write(Text(" "))

        # ── Último sync ────────────────────────────────────────────────────────
        with Session(engine) as session:
            last_sync = session.exec(
                sql_select(Activity)
                .where(Activity.command == "sync")
                .order_by(col(Activity.timestamp).desc())
            ).first()

        if last_sync:
            log.write(Text.assemble(
                ("Último sync  ", _MUTED),
                (self._rel(last_sync.timestamp), _SEC),
            ))
        else:
            log.write(Text("Sin syncs registrados", style=_MUTED))

        # ── Jira radar (se carga async en segundo plano) ──────────────────────
        import os as _os
        if _os.getenv("JIRA_URL"):
            self._fill_jira_radar()

    @work
    async def _fill_jira_radar(self) -> None:
        import asyncio as _aio
        from aicli.services.jira import fetch_my_issues

        try:
            radar = await _aio.get_running_loop().run_in_executor(None, fetch_my_issues)
        except Exception as e:
            try:
                log = self.query_one("#log-ahora", RichLog)
                log.write(Text(f"Jira no disponible: {e}", style=f"dim {_MUTED}"))
            except Exception:
                pass
            return

        try:
            log = self.query_one("#log-ahora", RichLog)
        except Exception:
            return

        _HIGH = {"High", "Highest", "Critical", "Alta", "Crítica"}

        def _short(s: str, n: int = 38) -> str:
            return s[:n - 1] + "…" if len(s) > n else s

        def _write_items(items: list) -> None:
            for item in items[:4]:
                hi = item["priority"] in _HIGH
                log.write(Text.assemble(
                    ("  ", ""),
                    (f"{item['id']:<12}", _ACCENT),
                    ("▲  " if hi else "·  ", _WARN if hi else _MUTED),
                    (_short(item["summary"]), _SEC),
                ))

        en_curso   = radar.get("en_curso", [])
        alta       = radar.get("alta_prioridad", [])
        reabiertos = radar.get("reabiertos", [])

        if not (en_curso or alta or reabiertos):
            return

        log.write(Text(" "))
        log.write(Text.assemble(("─" * 28, _BORDER)))
        log.write(Text.assemble(("JIRA  ", f"bold {_SECTION}"), ("radar de trabajo", _MUTED)))
        log.write(Text(" "))

        if en_curso:
            log.write(Text("EN CURSO", style=f"bold {_OK}"))
            _write_items(en_curso)
            log.write(Text(" "))
        if alta:
            log.write(Text("PENDIENTE · ALTA PRIORIDAD", style=f"bold {_WARN}"))
            _write_items(alta)
            log.write(Text(" "))
        if reabiertos:
            log.write(Text("REABIERTOS", style=f"bold {_ERROR}"))
            _write_items(reabiertos)

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

        loop = asyncio.get_running_loop()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                await loop.run_in_executor(
                    pool, _dispatch_tui, command, inputs, tui_console
                )
        except Exception as e:
            tui_console.print(f"\n[bold red]Error inesperado en {command}:[/bold red] {e}")
        finally:
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
    print("\033]0;MAGNA\007", end="", flush=True)
    MagnaApp().run()
