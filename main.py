from dotenv import load_dotenv
from pathlib import Path
import os
import time
import logging

Path.home().joinpath(".mycontext").mkdir(exist_ok=True)
Path.home().joinpath(".mycontext", "evidencias").mkdir(exist_ok=True)
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
from aicli.commands import status, init, archive, file_cmd, sync, task, claude_cmd, proyecto, revision
from aicli.db import init_db, engine

init_db()


def _purge_evidence() -> None:
    folder = Path.home() / ".mycontext" / "evidencias"
    limit = time.time() - 7 * 86400
    for file in folder.iterdir():
        try:
            if file.is_file() and file.stat().st_mtime < limit:
                file.unlink()
        except Exception:
            pass


def _capture_from_clipboard() -> str | None:
    """Lee imagen del portapapeles de Windows y la guarda en evidencias/."""
    import subprocess
    from datetime import datetime
    folder = Path.home() / ".mycontext" / "evidencias"
    name = f"captura_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    file_path = (folder / name).resolve()
    ps_path = str(file_path).replace("\\", "/")
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
        if r.returncode == 0 and file_path.exists():
            return str(file_path)
    except Exception:
        pass
    return None


def _ask_image() -> str | None:
    """Flujo estándar de adjuntar imagen: portapapeles primero, ruta manual como fallback."""
    use_clipboard = questionary.confirm(
        "  ¿Tenés una captura en el portapapeles?",
        default=False,
        style=_ESTILO_MENU,
    ).ask()

    if use_clipboard:
        captured = _capture_from_clipboard()
        if captured:
            console.print(f"  [bold green]✔[/bold green] [dim]Guardada: {captured}[/dim]")
            return captured
        console.print("  [bold yellow]⚠[/bold yellow] [dim]No hay imagen en el portapapeles.[/dim]")

    manual_path = questionary.text(
        "  Ruta de imagen (Enter para omitir)",
        style=_ESTILO_MENU,
    ).ask()
    return manual_path.strip() if manual_path and manual_path.strip() else None


_purge_evidence()

app = typer.Typer(help="AICLI — Motor de contexto inteligente para Claude Code")
app.add_typer(status.app, name="status")
app.add_typer(init.app, name="init")
app.add_typer(archive.app, name="archive")
app.add_typer(file_cmd.app, name="file")
app.add_typer(sync.app, name="sync")
app.add_typer(task.app, name="task")
app.add_typer(claude_cmd.app, name="claude")
app.add_typer(proyecto.app, name="proyecto")
app.add_typer(revision.app, name="revision")

console = Console()

_ESTILO_MENU = QStyle([
    ("qmark",       "fg:cyan bold"),
    ("question",    "fg:white bold"),
    ("pointer",     "fg:cyan bold"),
    ("highlighted", "fg:cyan bold"),
    ("selected",    "fg:cyan"),
    ("answer",      "fg:cyan bold"),
])


def _check_api_key() -> bool:
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
    env_path = Path.home() / ".mycontext" / ".env"
    env_path.parent.mkdir(exist_ok=True)
    env_path.write_text(f"ANTHROPIC_API_KEY={key}\n", encoding="utf-8")
    os.environ["ANTHROPIC_API_KEY"] = key

    console.print()
    console.print(f"  [bold green]✔[/bold green] API key guardada en [dim]{env_path}[/dim]")
    console.print()

    return True


def _select_project() -> bool:
    from sqlmodel import Session, select as sql_select
    from aicli.db.models import Project

    current_path = Path.cwd()

    with Session(engine) as session:
        current_project = session.exec(
            sql_select(Project).where(Project.path == str(current_path))
        ).first()

    if current_project:
        return True

    with Session(engine) as session:
        projects = list(session.exec(sql_select(Project)).all())

    console.print()
    console.print(Rule(title="[bold cyan]Seleccioná un proyecto[/bold cyan]", style="cyan"))
    console.print()

    if projects:
        choices = [
            questionary.Choice(f"  {p.name}   {p.path}", value=p.path)
            for p in projects
        ]
        choices.append(questionary.Choice("  Registrar proyecto nuevo...", value="__nuevo__"))

        selection = questionary.select(
            "¿Con qué proyecto querés trabajar?",
            choices=choices,
            style=_ESTILO_MENU,
        ).ask()

        if selection is None:
            return False

        if selection != "__nuevo__":
            selected_path = Path(selection)
            if not selected_path.exists():
                console.print(f"\n[bold red]Error:[/bold red] La ruta [bold]{selection}[/bold] ya no existe en disco.")
                return False
            os.chdir(selected_path)
            console.print(f"\n  [bold green]✔[/bold green] Trabajando en [dim]{selected_path}[/dim]")
            return True

    # Sin proyectos o eligió "Registrar nuevo"
    console.print("  Ingresá la ruta completa de tu proyecto:")
    console.print()

    path_str = questionary.text(
        "  Ruta del proyecto",
        style=_ESTILO_MENU,
    ).ask()

    if not path_str or not path_str.strip():
        return False

    new_path = Path(path_str.strip())
    if not new_path.exists():
        console.print(f"\n[bold red]Error:[/bold red] La ruta [bold]{new_path}[/bold] no existe.")
        return False

    os.chdir(new_path)
    console.print(f"\n  [bold green]✔[/bold green] Trabajando en [dim]{new_path}[/dim]")
    console.print("  [dim]Seleccioná [bold]ctx init[/bold] para registrar e indexar este proyecto.[/dim]")
    return True


def _show_menu() -> None:
    if not _check_api_key():
        raise typer.Exit(code=1)

    logo = pyfiglet.figlet_format("MAGNA", font="ansi_shadow")

    console.print()
    for line in logo.rstrip().splitlines():
        console.print(Align(Text(line, style="bold cyan"), align="center"))
        time.sleep(0.09)
    console.print()
    console.print(Align('[bold cyan]"You see what you believe..."[/bold cyan]', align="center"))
    console.print()

    if not _select_project():
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
                questionary.Choice("  ctx revision — Resolver críticos de revisión de PR",            value="revision"),
                questionary.Choice("  ctx task     — Lanzar Claude con contexto de una tarea",       value="task"),
                questionary.Choice("  ctx claude   — Lanzar Claude con contexto completo",           value="claude"),
                questionary.Choice("  ctx status   — Ver arquitectura documentada del proyecto",     value="status"),
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
            folder = questionary.text(
                "  ¿Qué carpeta documentar?  (ej: pagos  o  controllers/pagos)",
                style=_ESTILO_MENU
            ).ask()
            if not folder or not folder.strip():
                console.print("  [bold yellow]Aviso:[/bold yellow] Indicá una carpeta para continuar.")
                continue
            file_cmd.file_cmd(folder.strip())

        elif opcion == "archive":
            file_path = questionary.text(
                "  Ruta del archivo  (ej: pagos/PagosController.php)",
                style=_ESTILO_MENU
            ).ask()
            if not file_path or not file_path.strip():
                console.print("  [bold yellow]Aviso:[/bold yellow] Indicá la ruta del archivo para continuar.")
                continue
            archive.archive(file_path.strip())

        elif opcion == "sync":
            sync.sync()

        elif opcion == "revision":
            revision.revision()

        elif opcion == "retomar":
            from aicli.services.tickets import (
                load_tickets, format_history,
                save_active_ticket, read_active_ticket,
            )
            from rich.panel import Panel as RichPanel

            tickets = load_tickets()

            if tickets:
                ticket_choices = [
                    questionary.Choice(
                        f"  {tid}  ({len(data['rondas'])} ronda/s)",
                        value=tid,
                    )
                    for tid, data in tickets.items()
                ]
                ticket_choices.append(questionary.Choice("  Ingresar ID manualmente...", value="__manual__"))
                chosen_ticket = questionary.select(
                    "¿Qué ticket retomar?",
                    choices=ticket_choices,
                    style=_ESTILO_MENU,
                ).ask()
            else:
                chosen_ticket = "__manual__"

            if chosen_ticket == "__manual__":
                chosen_ticket = questionary.text(
                    "  ID del ticket (ej: PROJ-1234)",
                    style=_ESTILO_MENU,
                ).ask()

            if not chosen_ticket or not chosen_ticket.strip():
                console.print("  [bold yellow]Aviso:[/bold yellow] Indicá un ticket para continuar.")
                continue

            ticket_id = chosen_ticket.strip().upper()
            history = format_history(ticket_id, tickets)

            if history:
                console.print()
                console.print(RichPanel(history, title=f"[bold cyan]Historial {ticket_id}[/bold cyan]", border_style="cyan"))

            console.print()
            reason = questionary.text(
                "  Motivo de reapertura (pegá el comentario de QA)",
                style=_ESTILO_MENU,
            ).ask()

            if not reason or not reason.strip():
                console.print("  [bold yellow]Aviso:[/bold yellow] El motivo de reapertura es necesario.")
                continue

            image = _ask_image()
            file = questionary.text(
                "  Archivo específico (ej: pagos/PagosController.php) — Enter para omitir",
                style=_ESTILO_MENU,
            ).ask()

            save_active_ticket(ticket_id, reason.strip())

            reopen_task = f"[TICKET REABIERTO {ticket_id}] {reason.strip()}"
            clean_file = file.strip() if file and file.strip() else None
            task._execute_task(reopen_task, clean_file, image, ticket_history=history)

        elif opcion == "task":
            task_desc = questionary.text("  Describí la tarea", style=_ESTILO_MENU).ask()
            file = questionary.text(
                "  Ruta del archivo  (ej: pagos/PagosController.php) — Enter para omitir",
                style=_ESTILO_MENU,
            ).ask()
            image = _ask_image()
            if task_desc and task_desc.strip():
                clean_file = file.strip() if file and file.strip() else None
                task.task(task_desc.strip(), clean_file, image)

        elif opcion == "claude":
            claude_cmd.claude()

        elif opcion == "status":
            status.status()



@app.callback(invoke_without_command=True)
def bienvenida(ctx: typer.Context):
    if ctx.invoked_subcommand is not None:
        return
    _show_menu()


if __name__ == "__main__":
    app()