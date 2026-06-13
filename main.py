from dotenv import load_dotenv
from pathlib import Path
import os
import logging

Path.home().joinpath(".mycontext").mkdir(exist_ok=True)
logging.basicConfig(
    filename=Path.home() / ".mycontext" / "aicli.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    encoding="utf-8",
)

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
from aicli.db import init_db, engine

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


def _seleccionar_proyecto() -> bool:
    from sqlmodel import Session, select as sql_select
    from aicli.db.models import Project

    path_actual = Path.cwd()

    with Session(engine) as session:
        proyecto_actual = session.exec(
            sql_select(Project).where(Project.path == str(path_actual))
        ).first()

    if proyecto_actual:
        return True

    with Session(engine) as session:
        proyectos = list(session.exec(sql_select(Project)).all())

    console.print()
    console.print(Rule(title="[bold cyan]Seleccioná un proyecto[/bold cyan]", style="cyan"))
    console.print()

    if proyectos:
        opciones = [
            questionary.Choice(f"  {p.name}   {p.path}", value=p.path)
            for p in proyectos
        ]
        opciones.append(questionary.Choice("  Registrar proyecto nuevo...", value="__nuevo__"))

        eleccion = questionary.select(
            "¿Con qué proyecto querés trabajar?",
            choices=opciones,
            style=_ESTILO_MENU,
        ).ask()

        if eleccion is None:
            return False

        if eleccion != "__nuevo__":
            ruta_path = Path(eleccion)
            if not ruta_path.exists():
                console.print(f"\n[bold red]Error:[/bold red] La ruta [bold]{eleccion}[/bold] ya no existe en disco.")
                return False
            os.chdir(ruta_path)
            console.print(f"\n  [bold green]✔[/bold green] Trabajando en [dim]{ruta_path}[/dim]")
            return True

    # Sin proyectos o eligió "Registrar nuevo"
    console.print("  Ingresá la ruta completa de tu proyecto:")
    console.print()

    ruta_str = questionary.text(
        "  Ruta del proyecto",
        style=_ESTILO_MENU,
    ).ask()

    if not ruta_str or not ruta_str.strip():
        return False

    ruta_path = Path(ruta_str.strip())
    if not ruta_path.exists():
        console.print(f"\n[bold red]Error:[/bold red] La ruta [bold]{ruta_path}[/bold] no existe.")
        return False

    os.chdir(ruta_path)
    console.print(f"\n  [bold green]✔[/bold green] Trabajando en [dim]{ruta_path}[/dim]")
    console.print("  [dim]Seleccioná [bold]ctx init[/bold] para registrar e indexar este proyecto.[/dim]")
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

    if not _seleccionar_proyecto():
        raise typer.Exit(code=1)

    while True:
        console.print()
        console.print(Rule(style="cyan"))
        console.print()

        opcion = questionary.select(
            "¿Qué quieres hacer?",
            choices=[
                questionary.Choice("  ctx init        — Registrar e indexar el proyecto activo",      value="init"),
                questionary.Choice("  ctx module add  — Documentar un módulo específico",             value="module"),
                questionary.Choice("  ctx status      — Ver módulos ya documentados",                 value="status"),
                questionary.Choice("  ctx task        — Lanzar Claude con contexto de una tarea",     value="task"),
                questionary.Choice("  ctx claude      — Lanzar Claude con contexto completo",         value="claude"),
                questionary.Choice("  ctx snapshot    — Guardar punto de restauración",               value="snapshot"),
                questionary.Choice("  Salir",                                                         value="salir"),
            ],
            style=_ESTILO_MENU,
        ).ask()

        if opcion is None or opcion == "salir":
            console.print("\n  [dim]Hasta luego.[/dim]\n")
            break

        console.print()

        if opcion == "init":
            init.init()
        elif opcion == "module":
            nombre = questionary.text("  Nombre del módulo", style=_ESTILO_MENU).ask()
            archivo = questionary.text("  Ruta del archivo  (ej: aicli/commands/init.py)", style=_ESTILO_MENU).ask()
            if nombre and archivo:
                module.add(nombre.strip(), archivo.strip())
        elif opcion == "status":
            status.status()
        elif opcion == "task":
            tarea = questionary.text("  Describí la tarea", style=_ESTILO_MENU).ask()
            if tarea and tarea.strip():
                task.task(tarea.strip())
        elif opcion == "claude":
            claude_cmd.claude()
        elif opcion == "snapshot":
            snapshot.snapshot()


@app.callback(invoke_without_command=True)
def bienvenida(ctx: typer.Context):
    if ctx.invoked_subcommand is not None:
        return
    _mostrar_menu()


if __name__ == "__main__":
    app()
