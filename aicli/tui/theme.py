"""
MAGNA visual identity — Noche Estrellada palette.
El negro de la terminal es el lienzo. Solo se pintan superficies explícitas.
Single source of truth para todo output Rich/Textual.
"""
from contextlib import contextmanager
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

# ─── Noche Estrellada Palette ─────────────────────────────────────────────────
#
#  canvas         → #000000  — la terminal del usuario. NUNCA se pinta.
#  elevated       → #0D1120  — superficies explícitas (paneles, modales)
#  hover          → #161d33  — estado hover / focus de superficie
#  selection      → #4A3D1A  — highlight de selección (tinte dorado)

ACCENT   = "#FFB703"    # accent.primary       — dorado luna
SECTION  = "#5B8DEF"    # accent_secondary.info — azul cobalto
BORDER   = "#242C45"    # border.subtle
GLOW     = "#E8A20A"    # accent.hover
ELEVATED = "#0D1120"    # surface.elevated
HOVER_BG = "#161d33"    # surface.hover

_OK      = "#4ADE80"    # state.success
_WARN    = "#FBBF24"    # state.warning
_ERROR   = "#F87171"    # state.error
_MID     = "#3A4468"    # border.active (puntos separadores)
_SEC     = "#AAB4D4"    # text.secondary — texto secundario visible
_MUTED   = "#5E6A94"    # text.muted     — hints, timestamps, placeholders

# Aliases públicos para importar desde comandos
OK      = _OK
WARN    = _WARN
ERROR   = _ERROR
MID     = _MID
MUTED   = _MUTED
SEC     = _SEC

# Backwards-compat: BG apunta a ELEVATED (el único fondo que se pinta)
BG = ELEVATED

COLOR_OK      = f"bold {_OK}"
COLOR_WARN    = f"bold {_WARN}"
COLOR_ERROR   = f"bold {_ERROR}"
COLOR_DIM     = f"{_SEC}"
COLOR_PRIMARY = "bold #F1F3F9"
SPINNER       = "dots3"
SPINNER_STYLE = ACCENT

# Questionary style (prompt_toolkit true-color)
Q_STYLE_ARGS = [
    ("qmark",       f"fg:{ACCENT} bold"),
    ("question",    "fg:#F1F3F9 bold"),
    ("pointer",     f"fg:{ACCENT} bold"),
    ("highlighted", f"fg:{ACCENT} bold"),
    ("selected",    f"fg:{GLOW}"),
    ("answer",      f"fg:{ACCENT} bold"),
]


# ─── Structure ────────────────────────────────────────────────────────────────

def print_header(console: Console, command: str, description: str = "") -> None:
    console.print()
    label = Text()
    label.append("MAGNA", style=f"bold {ACCENT}")
    label.append("  ·  ", style=f"{_MID}")
    label.append(command, style="bold #F1F3F9")
    if description:
        label.append(f"  {description}", style=f"{_SEC}")
    console.print(Rule(label, style=ACCENT))
    console.print()


def print_footer(console: Console) -> None:
    console.print()
    console.print(Rule(style=BORDER))
    console.print()


def magna_section(console: Console, title: str) -> None:
    console.print()
    console.print(Rule(f"[{_MUTED}]{title}[/{_MUTED}]", style=BORDER))
    console.print()


# ─── Loading ──────────────────────────────────────────────────────────────────

@contextmanager
def magna_status(console: Console, message: str):
    with console.status(
        f"[{ACCENT}]{message}[/{ACCENT}]",
        spinner=SPINNER,
        spinner_style=SPINNER_STYLE,
    ):
        yield


# ─── Output messages ──────────────────────────────────────────────────────────

def magna_ok(console: Console, message: str) -> None:
    console.print(f"  [bold {_OK}]✔[/bold {_OK}]  [{_SEC}]{message}[/{_SEC}]")


def magna_warn(console: Console, message: str) -> None:
    console.print(f"  [bold {_WARN}]⚠[/bold {_WARN}]  [{_WARN}]{message}[/{_WARN}]")


def magna_error(console: Console, message: str) -> None:
    console.print(f"  [bold {_ERROR}]✖[/bold {_ERROR}]  [{_ERROR}]{message}[/{_ERROR}]")


def magna_info(console: Console, message: str) -> None:
    console.print(f"  [{_SEC}]{message}[/{_SEC}]")


# ─── Panels ───────────────────────────────────────────────────────────────────

def magna_panel(console: Console, title: str, content, success: bool = False) -> None:
    border = _OK if success else ACCENT
    console.print(Panel(
        content,
        title=f"[bold {ACCENT}]{title}[/bold {ACCENT}]",
        border_style=border,
    ))


def magna_task_plan(console: Console, modules: list, brief: str) -> None:
    """Card visual del plan de implementación — paleta Noche Estrellada."""
    # Línea de módulos
    mod_text = Text()
    for i, m in enumerate(modules):
        if i:
            mod_text.append("  ·  ", style=_MID)
        mod_text.append(getattr(m, "name", str(m)), style=f"bold {SECTION}")

    # Plan: cada línea con ◆ dorado
    body = Text()
    body.append("\n")
    for line in brief.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        body.append(f"  ◆  ", style=ACCENT)
        body.append(f"{line}\n", style="#F1F3F9")

    content = Text.assemble(
        ("  módulos: ", _MUTED), mod_text, "\n",
        (f"  {'─' * 52}\n", BORDER),
        body,
    )

    console.print(Panel(
        content,
        title=f"[bold {ACCENT}]◆  Plan de implementación[/bold {ACCENT}]",
        subtitle=f"[{_MUTED}]claude-sonnet-4-6  ·  extended thinking[/{_MUTED}]",
        border_style=ACCENT,
        padding=(0, 1),
    ))


# ─── Tables ───────────────────────────────────────────────────────────────────

def magna_table(*columns: str) -> Table:
    t = Table(style=ACCENT, show_header=True, header_style=f"bold {ACCENT}")
    for col in columns:
        t.add_column(col)
    return t
