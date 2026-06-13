from dotenv import load_dotenv
from pathlib import Path
import os

# Carga en orden de prioridad: variable de sistema → .env local → ~/.mycontext/.env
load_dotenv()
load_dotenv(dotenv_path=Path.home() / ".mycontext" / ".env", override=False)

import typer
import pyfiglet
import questionary
from questionary import Style as QStyle
from rich.console import Console
from rich.align import Align
from rich.rule import Rule
from rich.text import Text
from aicli.commands import status, init, module, task, claude_cmd, snapshot
from aicli.db import init_db

init_db()

app = typer.Typer(help="AICLI — Motor de contexto inteligente para Claude Code")
app.add_typer(status.app, name="status")
app.add_typer(init.app, name="init")
app.add_typer(module.app, name="module")
app.add_typer(task.app, name="task")
app.add_typer(claude_cmd.app, name="claude")
app.add_typer(snapshot.app, name="snapshot")

console = Console()

_ESTILO_MENU = QStyle([
    ("qmark",       "fg:cyan bold"),
    ("question",    "fg:white bold"),
    ("pointer",     "fg:cyan bold"),
    ("highlighted", "fg:cyan bold"),
    ("selected",    "fg:cyan"),
    ("answer",      "fg:cyan bold"),
])


def _verificar_api_key() -> bool:
    if os.getenv("ANTHROPIC_API_KEY"):
        return True

    console.print()
    console.print(Rule(title="[bold cyan]Configuración inicial[/bold cyan]", style="cyan"))
    console.print()
    console.print("  AICLI necesita tu [bold]API key de Anthropic[/bold] para funcionar.")
    console.print()
    console.print("  Conseguila en: [bold cyan]console.anthropic.com[/bold cyan] → API Keys")
    console.print()

    key = questionary.password("  Pegá tu ANTHROPIC_API_KEY", style=_ESTILO_MENU).ask()

    if not key or not key.strip():
        console.print("\n[bold red]Error:[/bold red] La key no puede estar vacía.")
        return False

    key = key.strip()
    ruta_env = Path.home() / ".mycontext" / ".env"
    ruta_env.parent.mkdir(exist_ok=True)
    ruta_env.write_text(f"ANTHROPIC_API_KEY={key}\n", encoding="utf-8")
    os.environ["ANTHROPIC_API_KEY"] = key

    console.print()
    console.print(f"  [bold green]✔[/bold green] API key guardada en [dim]{ruta_env}[/dim]")
    console.print()

    return True


def _mostrar_menu() -> None:
    if not _verificar_api_key():
        raise typer.Exit(code=1)

    logo = pyfiglet.figlet_format("AICLI", font="slant")

    console.print()
    console.print(Align(Text(logo.rstrip(), style="bold cyan"), align="center"))
    console.print()
    console.print(Align("[dim]Motor de contexto inteligente para Claude Code[/dim]", align="center"))
    console.print()
    console.print(Align(
        '[italic cyan]"La única persona que necesitas para lograr grandes cosas eres tú mismo"[/italic cyan]',
        align="center"
    ))
    console.print()
    console.print(Rule(style="cyan"))
    console.print()

    opcion = questionary.select(
        "¿Qué quieres hacer?",
        choices=[
            questionary.Choice("  ctx init    — Registrar e indexar el proyecto activo",   value="1"),
            questionary.Choice("  ctx status  — Ver módulos ya documentados",               value="2"),
            questionary.Choice("  ctx claude  — Lanzar Claude Code con contexto completo",  value="3"),
        ],
        style=_ESTILO_MENU,
    ).ask()

    if opcion is None:
        return

    console.print()

    if opcion == "1":
        init.init()
    elif opcion == "2":
        status.status()
    elif opcion == "3":
        claude_cmd.claude()


@app.callback(invoke_without_command=True)
def bienvenida(ctx: typer.Context):
    if ctx.invoked_subcommand is not None:
        return
    _mostrar_menu()


if __name__ == "__main__":
    app()