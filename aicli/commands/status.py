import typer
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project, Module

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def status():
    """Muestra la arquitectura documentada del proyecto agrupada por carpeta."""
    path = Path.cwd()

    with Session(engine) as session:
        proyecto = session.exec(select(Project).where(Project.path == str(path))).first()

    if not proyecto:
        console.print("[bold yellow]Aviso:[/bold yellow] Este directorio no está registrado. Ejecutá [bold]ctx init[/bold] primero.")
        return

    with Session(engine) as session:
        modulos = list(session.exec(select(Module).where(Module.project_id == proyecto.id)).all())

    if not modulos:
        console.print(Panel(
            "[yellow]Todavía no hay módulos documentados.[/yellow]\n\n"
            "Ejecutá [bold cyan]ctx init[/bold cyan] para mapear la arquitectura del proyecto.",
            title="Sin documentación",
            border_style="yellow",
        ))
        return

    carpetas: dict[str, list[Module]] = {}
    for m in modulos:
        partes = Path(m.file_path).parts
        carpeta = partes[0] if len(partes) > 1 else "[raíz]"
        carpetas.setdefault(carpeta, []).append(m)

    def _ultima(mods: list[Module]) -> float:
        return max((m.last_updated_at or 0.0) for m in mods)

    carpetas_ordenadas = sorted(carpetas.items(), key=lambda x: _ultima(x[1]), reverse=True)

    tabla = Table(style="cyan", show_header=True, header_style="bold cyan")
    tabla.add_column("Carpeta", style="bold", min_width=22)
    tabla.add_column("Módulos", justify="right", style="dim")
    tabla.add_column("Última doc", style="dim")

    for carpeta, mods in carpetas_ordenadas:
        ts = _ultima(mods)
        fecha = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "—"
        tabla.add_row(f"{carpeta}/", str(len(mods)), fecha)

    console.print()
    console.print(Panel(
        tabla,
        title=f"[bold cyan]Arquitectura documentada — {proyecto.name}[/bold cyan]",
        border_style="cyan",
    ))
    console.print(f"  [dim]{len(modulos)} módulos en {len(carpetas)} carpetas[/dim]")
    console.print()
    console.print("  [dim]¿No ves una carpeta? Ejecutá [bold cyan]ctx init[/bold cyan] para actualizar la arquitectura.[/dim]")