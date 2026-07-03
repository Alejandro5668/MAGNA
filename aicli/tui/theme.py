"""
MAGNA visual identity — shared Rich utilities for all commands.

Usage in any command:
    from aicli.tui.theme import magna_status, magna_ok, magna_panel, ...

All output goes through these functions so the visual language stays
consistent regardless of which command is running.
"""

from contextlib import contextmanager
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text


# ─── Palette (single source of truth) ────────────────────────────────────────

ACCENT        = "cyan"
COLOR_OK      = "bold green"
COLOR_WARN    = "bold yellow"
COLOR_ERROR   = "bold red"
COLOR_DIM     = "dim"
COLOR_PRIMARY = "bold white"
SPINNER       = "dots3"
SPINNER_STYLE = "cyan"


# ─── Structure ────────────────────────────────────────────────────────────────

def print_header(console: Console, command: str, description: str = "") -> None:
    """Full MAGNA header — printed once at the start of each suspended command."""
    console.print()
    label = Text()
    label.append("MAGNA", style="bold cyan")
    label.append("  ·  ", style="dim")
    label.append(command, style="bold white")
    if description:
        label.append(f"  {description}", style="dim")
    console.print(Rule(label, style="cyan"))
    console.print()


def print_footer(console: Console) -> None:
    """MAGNA footer — printed once at the end of each suspended command."""
    console.print()
    console.print(Rule(style="cyan"))
    console.print()


def magna_section(console: Console, title: str) -> None:
    """Lightweight mid-command section separator."""
    console.print()
    console.print(Rule(f"[dim]{title}[/dim]", style="#1e1e1e"))
    console.print()


# ─── Loading ──────────────────────────────────────────────────────────────────

@contextmanager
def magna_status(console: Console, message: str):
    """
    Standard MAGNA loading spinner.

    Usage:
        with magna_status(console, "Calling Claude API..."):
            result = client.messages.create(...)
    """
    with console.status(
        f"[cyan]{message}[/cyan]",
        spinner=SPINNER,
        spinner_style=SPINNER_STYLE,
    ):
        yield


# ─── Output messages ──────────────────────────────────────────────────────────

def magna_ok(console: Console, message: str) -> None:
    """Success confirmation line."""
    console.print(f"  [bold green]✔[/bold green]  {message}")


def magna_warn(console: Console, message: str) -> None:
    """Non-fatal warning line."""
    console.print(f"  [bold yellow]⚠[/bold yellow]  [yellow]{message}[/yellow]")


def magna_error(console: Console, message: str) -> None:
    """Error line — use before returning or raising."""
    console.print(f"  [bold red]✖[/bold red]  [red]{message}[/red]")


def magna_info(console: Console, message: str) -> None:
    """Dim informational line for secondary details."""
    console.print(f"  [dim]{message}[/dim]")


# ─── Panels ───────────────────────────────────────────────────────────────────

def magna_panel(console: Console, title: str, content) -> None:
    """
    Standard MAGNA panel with cyan border.

    `content` can be a string, Rich renderable, or Table.
    """
    console.print(
        Panel(
            content,
            title=f"[bold cyan]{title}[/bold cyan]",
            border_style="cyan",
        )
    )


# ─── Tables ───────────────────────────────────────────────────────────────────

def magna_table(*columns: str) -> Table:
    """
    Standard MAGNA table factory.

    Usage:
        t = magna_table("Column A", "Column B")
        t.add_row("value", "value")
        console.print(t)
    """
    t = Table(style="cyan", show_header=True, header_style="bold cyan")
    for col in columns:
        t.add_column(col)
    return t
