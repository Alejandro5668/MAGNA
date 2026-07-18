from __future__ import annotations
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static, Input, Label, Rule, RichLog, TextArea
from textual.widget import Widget
from textual.widgets.option_list import Option
from textual.containers import Container, Vertical
from textual.binding import Binding
from textual import work
from textual.message import Message

# ─── Noche Estrellada — mirrors theme.py ──────────────────────────────────────
_ACCENT   = "#FFB703"
_SECTION  = "#5B8DEF"
_BORDER   = "#242C45"
_BORDER_A = "#3A4468"
_GLOW     = "#E8A20A"
_ELEVATED = "#0D1120"
_HOVER    = "#161d33"
_SELECT   = "#4A3D1A"
_OK       = "#4ADE80"
_WARN     = "#FBBF24"
_ERROR    = "#F87171"
_MID      = "#3A4468"
_SEC      = "#AAB4D4"
_MUTED    = "#5E6A94"

_HELP_ROWS = [
    ("1 – 7",    "Ejecutar comando directamente"),
    ("j / ↓",    "Bajar en menú / tickets"),
    ("k / ↑",    "Subir en menú / tickets"),
    ("g",        "Ir al primer ítem"),
    ("G",        "Ir al último ítem"),
    ("h",        "Colapsar sección"),
    ("l",        "Expandir sección"),
    ("Enter",    "Seleccionar / iniciar tarea"),
    ("t",        "Enfocar panel de tickets"),
    ("r",        "Refrescar tickets (en panel)"),
    ("p",        "Cambiar proyecto activo"),
    ("?",        "Esta ayuda"),
    ("Esc",      "Volver / Cancelar"),
    ("q",        "Salir"),
]

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
                f"[bold {_ACCENT}][[esc]][/bold {_ACCENT}] [{_SEC}]cerrar[/{_SEC}]",
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
                f"[bold {_ACCENT}][[↵]][/bold {_ACCENT}] [{_SEC}]confirmar[/{_SEC}]"
                f"  [{_MUTED}]·[/{_MUTED}]  [bold {_ERROR}][[esc]][/bold {_ERROR}] [{_SEC}]cancelar[/{_SEC}]",
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
    """Modal multilinea para descripciones de tarea. Ctrl+S confirma."""

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
                f"[bold {_ACCENT}][[ctrl+s]][/bold {_ACCENT}] [{_SEC}]confirmar[/{_SEC}]"
                f"  [{_MUTED}]·[/{_MUTED}]  [bold {_ERROR}][[esc]][/bold {_ERROR}] [{_SEC}]cancelar[/{_SEC}]",
                id="tam-hint", markup=True,
            )

    def on_mount(self) -> None:
        ta = self.query_one(TextArea)
        ta.focus()
        if self._initial_text:
            ta.load_text(self._initial_text)

    def on_key(self, event) -> None:
        if event.key == "ctrl+s":
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
        confirm_label = "sí" if self._default else "no"
        with Container(id="cf-box"):
            yield Static("━━━  MAGNA  ━━━", id="cf-header")
            yield Label(self._prompt, id="cf-prompt")
            yield Label(
                f"[bold {_ACCENT}][[↵]][/bold {_ACCENT}] [{_SEC}]{confirm_label}[/{_SEC}]"
                f"  [{_MUTED}]·[/{_MUTED}]  [bold {_ERROR}][[esc]][/bold {_ERROR}] [{_SEC}]cancelar[/{_SEC}]",
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
                f"[bold {_ACCENT}][[↵]][/bold {_ACCENT}] [{_SEC}]continuar[/{_SEC}]"
                f"  [{_MUTED}]·[/{_MUTED}]  "
                f"[bold {_ERROR}][[esc]][/bold {_ERROR}] [{_SEC}]cancelar[/{_SEC}]",
                id="jc-hint", markup=True,
            )

    def action_proceed(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
