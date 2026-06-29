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
        project = session.exec(select(Project).where(Project.path == str(path))).first()

    if not project:
        console.print("[bold yellow]Aviso:[/bold yellow] Este directorio no está registrado. Ejecutá [bold]ctx init[/bold] primero.")
        return

    with Session(engine) as session:
        modules = list(session.exec(select(Module).where(Module.project_id == project.id)).all())

    if not modules:
        console.print(Panel(
            "[yellow]Todavía no hay módulos documentados.[/yellow]\n\n"
            "Ejecutá [bold cyan]ctx init[/bold cyan] para mapear la arquitectura del proyecto.",
            title="Sin documentación",
            border_style="yellow",
        ))
        return

    folders: dict[str, list[Module]] = {}
    for m in modules:
        parts = Path(m.file_path).parts
        folder = parts[0] if len(parts) > 1 else "[raíz]"
        folders.setdefault(folder, []).append(m)

    def _last_updated(mods: list[Module]) -> float:
        return max((m.last_updated_at or 0.0) for m in mods)

    sorted_folders = sorted(folders.items(), key=lambda x: _last_updated(x[1]), reverse=True)

    table = Table(style="cyan", show_header=True, header_style="bold cyan")
    table.add_column("Carpeta", style="bold", min_width=22)
    table.add_column("Módulos", justify="right", style="dim")
    table.add_column("Última doc", style="dim")

    for folder, mods in sorted_folders:
        ts = _last_updated(mods)
        date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "—"
        table.add_row(f"{folder}/", str(len(mods)), date)

    console.print()
    console.print(Panel(
        table,
        title=f"[bold cyan]Arquitectura documentada — {project.name}[/bold cyan]",
        border_style="cyan",
    ))
    console.print(f"  [dim]{len(modules)} módulos en {len(folders)} carpetas[/dim]")
    console.print()
    console.print("  [dim]¿No ves una carpeta? Ejecutá [bold cyan]ctx init[/bold cyan] para actualizar la arquitectura.[/dim]")