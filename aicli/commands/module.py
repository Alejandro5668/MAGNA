import typer
import time
from rich.console import Console, Group
from rich.panel import Panel
from pathlib import Path
from datetime import datetime
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project, Module
from aicli.services.indexer import generar_contenido_modulo, modulo_necesita_actualizacion

app = typer.Typer()
console = Console()


@app.command("add")
def add(
    name: str = typer.Argument(..., help="Nombre del módulo a documentar"),
    file: str = typer.Argument(..., help="Ruta relativa al archivo principal del módulo"),
):
    """Documenta un módulo con IA. Si ya existe y cambió, lo actualiza."""
    path = Path.cwd()

    with Session(engine) as session:
        proyecto = session.exec(select(Project).where(Project.path == str(path))).first()

    if not proyecto:
        console.print(Panel(
            "Este directorio no está registrado. Ejecutá [bold]ctx init[/bold] primero.",
            title="Error",
            border_style="red"
        ))
        raise typer.Exit(code=1)

    ruta_archivo = path / file
    if not ruta_archivo.exists():
        console.print(f"[bold red]Error:[/bold red] No se encontró el archivo [bold]{file}[/bold]")
        raise typer.Exit(code=1)

    with Session(engine) as session:
        modulo_existente = session.exec(select(Module).where(Module.file_path == str(file))).first()

    if modulo_existente and not modulo_necesita_actualizacion(file, path, modulo_existente):
        console.print(Panel(
            f"[cyan]El módulo [bold]{modulo_existente.name}[/bold] ya está al día — sin cambios desde la última documentación.[/cyan]",
            title="Sin cambios",
            border_style="yellow"
        ))
        return

    fuente = ruta_archivo.read_text(encoding="utf-8")

    with console.status("[bold cyan]Generando documentación...[/bold cyan]", spinner="dots3", spinner_style="cyan"):
        contenido_md = generar_contenido_modulo(name, file, fuente)

    directorio = Path.home() / ".mycontext" / "projects" / str(proyecto.id)
    directorio.mkdir(parents=True, exist_ok=True)
    archivo_md = directorio / f"{name}.md"
    archivo_md.write_text(contenido_md, encoding="utf-8")

    with Session(engine) as session:
        if modulo_existente:
            m = session.get(Module, modulo_existente.id)
            m.content_path = str(archivo_md)
            m.last_updated_at = time.time()
            session.add(m)
            session.commit()
            titulo = "Módulo actualizado"
        else:
            modulo = Module(
                project_id=proyecto.id,
                name=name,
                description=contenido_md.splitlines()[0].lstrip("# "),
                file_path=file,
                content_path=str(archivo_md),
                created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                last_updated_at=time.time(),
            )
            session.add(modulo)
            session.commit()
            titulo = "Módulo registrado"

    contenido_panel = Group(
        f"[bold cyan]✔ Módulo [bold]{name}[/bold] documentado[/bold cyan]",
        f"[bold dim]Archivo fuente: {file}[/bold dim]",
        f"[bold dim]Documentación: {archivo_md}[/bold dim]",
    )
    console.print(Panel(contenido_panel, title=titulo, border_style="green"))