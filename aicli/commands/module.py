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
    ruta: str = typer.Argument(..., help="Ruta del archivo a documentar (ej: pagos/PagosController.php)"),
):
    """Documenta un archivo con IA siguiendo la estructura modulo/archivo.php."""
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

    ruta_archivo = path / ruta
    if not ruta_archivo.exists():
        console.print(f"[bold red]Error:[/bold red] No se encontró [bold]{ruta}[/bold]")
        raise typer.Exit(code=1)

    # Nombre derivado del path: pagos/PagosController.php → PagosController
    name = Path(ruta).stem

    with Session(engine) as session:
        modulo_existente = session.exec(
            select(Module).where(Module.file_path == ruta, Module.project_id == proyecto.id)
        ).first()

    if modulo_existente and not modulo_necesita_actualizacion(ruta, path, modulo_existente):
        console.print(Panel(
            f"[cyan][bold]{ruta}[/bold] ya está al día — sin cambios desde la última documentación.[/cyan]",
            title="Sin cambios",
            border_style="yellow"
        ))
        return

    fuente = ruta_archivo.read_text(encoding="utf-8")

    with console.status(f"[bold cyan]Documentando {ruta}...[/bold cyan]", spinner="dots3", spinner_style="cyan"):
        contenido_md, tokens = generar_contenido_modulo(name, ruta, fuente)

    # Espeja la estructura del proyecto: pagos/X.php → ~/.mycontext/projects/42/pagos/X.md
    base = Path.home() / ".mycontext" / "projects" / str(proyecto.id)
    archivo_md = base / Path(ruta).with_suffix(".md")
    archivo_md.parent.mkdir(parents=True, exist_ok=True)
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
                file_path=ruta,
                content_path=str(archivo_md),
                created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                last_updated_at=time.time(),
            )
            session.add(modulo)
            session.commit()
            titulo = "Módulo registrado"

    console.print(Panel(
        Group(
            f"[bold cyan]✔ {ruta} documentado[/bold cyan]",
            f"[bold dim]Módulo: {name}[/bold dim]",
            f"[bold dim]Doc: {archivo_md}[/bold dim]",
            f"[bold dim]Tokens: {tokens:,}[/bold dim]",
        ),
        title=titulo,
        border_style="green"
    ))