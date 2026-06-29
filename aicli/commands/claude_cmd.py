import typer
import logging
from rich.console import Console
from pathlib import Path
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project, Module
from aicli.services.builder import build_context
from aicli.services.caller import launch_claude

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def claude():
    """Inyecta el contexto completo del proyecto y lanza Claude Code."""
    path = Path.cwd()

    with Session(engine) as session:
        project = session.exec(select(Project).where(Project.path == str(path))).first()

    if not project:
        console.print("[bold red]Error:[/bold red] Este directorio no está registrado. Ejecutá [bold]ctx init[/bold] primero.")
        raise typer.Exit(code=1)

    with Session(engine) as session:
        modules = list(session.exec(select(Module).where(Module.project_id == project.id)).all())

    if not modules:
        console.print("[bold yellow]Aviso:[/bold yellow] No hay módulos documentados. Ejecutá [bold]ctx init[/bold] primero.")
        raise typer.Exit(code=1)

    try:
        console.print(f"[bold cyan]Cargando contexto completo...[/bold cyan] [dim]{len(modules)} módulos[/dim]")
        context = build_context(modules)
        launch_claude(context)
    except Exception as e:
        logging.error("ctx claude falló: %s", e, exc_info=True)
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)