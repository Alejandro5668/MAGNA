from dotenv import load_dotenv
from pathlib import Path
import os
import logging

Path.home().joinpath(".mycontext").mkdir(exist_ok=True)
logging.basicConfig(
    filename=Path.home() / ".mycontext" / "aicli_log.log",
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
from aicli.commands import status, init, archive, file_cmd, sync, task, claude_cmd, snapshot, proyecto
from aicli.db import init_db, engine

init_db()

app = typer.Typer(help="AICLI — Motor de contexto inteligente para Claude Code")
app.add_typer(status.app, name="status")
app.add_typer(init.app, name="init")
app.add_typer(archive.app, name="archive")
app.add_typer(file_cmd.app, name="file")
app.add_typer(sync.app, name="sync")
app.add_typer(task.app, name="task")
app.add_typer(claude_cmd.app, name="claude")
app.add_typer(snapshot.app, name="snapshot")
app.add_typer(proyecto.app, name="proyecto")

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
                questionary.Choice("  ctx init     — Mapear arquitectura del proyecto",              value="init"),
                questionary.Choice("  ctx proyecto — Generar conocimiento estructural del proyecto",  value="proyecto"),
                questionary.Choice("  ctx file     — Documentar una carpeta/zona en profundidad",    value="file"),
                questionary.Choice("  ctx archive  — Analizar y documentar un archivo específico",   value="archive"),
                questionary.Choice("  ctx sync     — Sincronizar documentación post-tarea",          value="sync"),
                questionary.Choice("  ctx retomar  — Retomar ticket reabierto por QA",               value="retomar"),
                questionary.Choice("  ctx task     — Lanzar Claude con contexto de una tarea",       value="task"),
                questionary.Choice("  ctx claude   — Lanzar Claude con contexto completo",           value="claude"),
                questionary.Choice("  ctx status   — Ver módulos documentados",                      value="status"),
                questionary.Choice("  ctx snapshot — Guardar punto de restauración",                 value="snapshot"),
                questionary.Choice("  Salir",                                                        value="salir"),
            ],
            style=_ESTILO_MENU,
        ).ask()

        if opcion is None or opcion == "salir":
            console.print("\n  [dim]Hasta luego.[/dim]\n")
            break

        console.print()

        if opcion == "init":
            init.init()

        elif opcion == "proyecto":
            proyecto.proyecto()

        elif opcion == "file":
            carpeta = questionary.text(
                "  ¿Qué carpeta documentar?  (ej: pagos  o  controllers/pagos)",
                style=_ESTILO_MENU
            ).ask()
            if not carpeta or not carpeta.strip():
                console.print("  [bold yellow]Aviso:[/bold yellow] Indicá una carpeta para continuar.")
                continue
            file_cmd.file_cmd(carpeta.strip())

        elif opcion == "archive":
            ruta = questionary.text(
                "  Ruta del archivo  (ej: pagos/PagosController.php)",
                style=_ESTILO_MENU
            ).ask()
            if not ruta or not ruta.strip():
                console.print("  [bold yellow]Aviso:[/bold yellow] Indicá la ruta del archivo para continuar.")
                continue
            archive.archive(ruta.strip())

        elif opcion == "sync":
            sync.sync()

        elif opcion == "retomar":
            from aicli.services.tickets import (
                cargar_tickets, formatear_historial,
                guardar_ticket_activo, leer_ticket_activo,
            )
            from rich.panel import Panel as RichPanel

            tickets = cargar_tickets()

            if tickets:
                opciones_tickets = [
                    questionary.Choice(
                        f"  {tid}   {datos['descripcion']}  ({len(datos['rondas'])} ronda/s)",
                        value=tid,
                    )
                    for tid, datos in tickets.items()
                ]
                opciones_tickets.append(questionary.Choice("  Ingresar ID manualmente...", value="__manual__"))
                ticket_elegido = questionary.select(
                    "¿Qué ticket retomar?",
                    choices=opciones_tickets,
                    style=_ESTILO_MENU,
                ).ask()
            else:
                ticket_elegido = "__manual__"

            if ticket_elegido == "__manual__":
                ticket_elegido = questionary.text(
                    "  ID del ticket (ej: PROJ-1234)",
                    style=_ESTILO_MENU,
                ).ask()

            if not ticket_elegido or not ticket_elegido.strip():
                console.print("  [bold yellow]Aviso:[/bold yellow] Indicá un ticket para continuar.")
                continue

            ticket_id = ticket_elegido.strip().upper()
            historial = formatear_historial(ticket_id, tickets)

            if historial:
                console.print()
                console.print(RichPanel(historial, title=f"[bold cyan]Historial {ticket_id}[/bold cyan]", border_style="cyan"))

            console.print()
            motivo = questionary.text(
                "  Motivo de reapertura (pegá el comentario de QA)",
                style=_ESTILO_MENU,
            ).ask()

            if not motivo or not motivo.strip():
                console.print("  [bold yellow]Aviso:[/bold yellow] El motivo de reapertura es necesario.")
                continue

            imagen = questionary.text(
                "  Imagen de evidencia (ruta local) — Enter para omitir",
                style=_ESTILO_MENU,
            ).ask()
            archivo = questionary.text(
                "  Archivo específico (ej: pagos/PagosController.php) — Enter para omitir",
                style=_ESTILO_MENU,
            ).ask()

            guardar_ticket_activo(ticket_id, motivo.strip())

            tarea_retomar = f"[TICKET REABIERTO {ticket_id}] {motivo.strip()}"
            archivo_limpio = archivo.strip() if archivo and archivo.strip() else None
            imagen_limpia = imagen.strip() if imagen and imagen.strip() else None
            task._ejecutar_task(tarea_retomar, archivo_limpio, imagen_limpia, historial_ticket=historial)

        elif opcion == "task":
            tarea = questionary.text("  Describí la tarea", style=_ESTILO_MENU).ask()
            archivo = questionary.text(
                "  Ruta del archivo  (ej: pagos/PagosController.php) — Enter para omitir",
                style=_ESTILO_MENU,
            ).ask()
            imagen = questionary.text(
                "  Ruta de imagen de referencia  (ej: C:\\screenshots\\bug.png) — Enter para omitir",
                style=_ESTILO_MENU,
            ).ask()
            if tarea and tarea.strip():
                archivo_limpio = archivo.strip() if archivo and archivo.strip() else None
                imagen_limpia = imagen.strip() if imagen and imagen.strip() else None
                task.task(tarea.strip(), archivo_limpio, imagen_limpia)

        elif opcion == "claude":
            claude_cmd.claude()

        elif opcion == "status":
            status.status()

        elif opcion == "snapshot":
            snapshot.snapshot()


@app.callback(invoke_without_command=True)
def bienvenida(ctx: typer.Context):
    if ctx.invoked_subcommand is not None:
        return
    _mostrar_menu()


if __name__ == "__main__":
    app()