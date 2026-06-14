import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlmodel import Session, select, func
from aicli.db import engine
from aicli.db.models import Project, Module

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def status():
    """Muestra el estado actual del contexto: proyectos y módulos documentados."""
    with Session(engine) as session:
        total_proyectos = session.exec(select(func.count()).select_from(Project)).first()
        total_modulos = session.exec(select(func.count()).select_from(Module)).first()

    contenido = (
        f"[bold]Proyectos registrados:[/bold] [dim]{total_proyectos}[/dim]\n"
        f"[bold]Módulos documentados:[/bold] [dim]{total_modulos}[/dim]"
    )
    console.print(Panel(contenido, title="AICLI — Estado del contexto", border_style="cyan"))

    with Session(engine) as session:
        results = list(session.exec(select(Module.name, Module.description, Module.file_path)).all())

    if not results:
        console.print(Panel(
            "[yellow]Todavía no hay módulos documentados.[/yellow]\n\n"
            "Seleccioná [bold cyan]ctx init[/bold cyan] en el menú para escanear "
            "el proyecto activo y generar la documentación.",
            title="Sin documentación",
            border_style="yellow"
        ))
        return

    tabla = Table(style="cyan")
    tabla.add_column("Módulo", style="bold")
    tabla.add_column("Descripción")
    tabla.add_column("Archivo", style="dim")

    for m in results:
        tabla.add_row(m.name, m.description, m.file_path)

    console.print(tabla)