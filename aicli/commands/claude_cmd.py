import typer
import logging
from rich.console import Console
from pathlib import Path
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project, Module
from aicli.services.builder import build_context
from aicli.services.caller import launch_claude
from aicli.tui.theme import magna_error, magna_warn, magna_info, ACCENT

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def claude():
    """Inyecta el contexto completo del proyecto y lanza Claude Code."""
    path = Path.cwd()

    with Session(engine) as session:
        project = session.exec(select(Project).where(Project.path == str(path))).first()

    if not project:
        magna_error(console, "Este directorio no está registrado. Ejecutá ctx init primero.")
        raise typer.Exit(code=1)

    with Session(engine) as session:
        modules = list(session.exec(select(Module).where(Module.project_id == project.id)).all())

    if not modules:
        magna_warn(console, "No hay módulos documentados. Ejecutá ctx init primero.")
        raise typer.Exit(code=1)

    try:
        magna_info(console, f"Cargando contexto completo... {len(modules)} módulos")
        context = build_context(modules)
        launch_claude(context)
    except Exception as e:
        logging.error("ctx claude falló: %s", e, exc_info=True)
        magna_error(console, str(e))
        raise typer.Exit(code=1)
