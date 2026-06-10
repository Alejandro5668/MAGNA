import typer
from rich.console import Console, Group
from rich.panel import Panel
from pathlib import Path
from datetime import datetime
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project, Module
from aicli.services.indexer import generar_contenido_modulo

app = typer.Typer()
console = Console()

@app.command("add")
def add(
    name: str = typer.Argument(..., help="Nombre del modulo a documentar"),
    file: str = typer.Argument(..., help="Ruta relativa al archivo principal del modulo")
):

    with Session(engine) as session:
        statement = session.exec(select(Module).where(Module.file_path == str(file))).first()
        if statement:
            contenido_panel = Group(
                f"[cyan]El módulo [bold]{statement.name}[/bold] ya esta documentado[/cyan] ",
                "[bold]Si quieres actualizarlo, borra el módulo primero y vuelve a correr este comando.[/bold]"
            )
            console.print(Panel(
                contenido_panel,
                title="Aviso",
                border_style="yellow",
            ))
            raise typer.Exit(code=1)

    path = Path.cwd()

    with Session(engine) as session:
        proyecto = session.exec(select(Project).where(Project.path == str(path))).first()

        if not proyecto:
            mensaje = "Este directorio no esta registrado.  Ejecutá [bold]ctx init[/bold] primero."
            console.print(Panel(mensaje, title="Registro fallido", border_style = "red"))
            raise typer.Exit(code=1)

    ruta_archivo = path / file
    if not ruta_archivo.exists():
        console.print(f"[bold red]Error:[/bold red] No se encontró el archivo [bold]{file}[/bold]")
        raise typer.Exit(code=1)

    fuente = ruta_archivo.read_text(encoding="utf-8")

    with console.status("[bold cyan]Generando documentacion ...[/bold cyan]", spinner="dots3", spinner_style="cyan"):
        contenido_md = generar_contenido_modulo(name, file, fuente)

    # Creamos archivo en el directorio del contexto y lo llenamos con el contenido que nos trae CLAUDE
    directorio = Path.home() / ".mycontext" / "projects" / str(proyecto.id)
    directorio.mkdir(parents=True, exist_ok=True)
    archivo_md = directorio / f"{name}.md"
    archivo_md.write_text(contenido_md, encoding="utf-8")

    with Session(engine) as session:
        module = Module(
            project_id=proyecto.id,
            name=name,
            description=contenido_md.splitlines()[0].lstrip("# "),
            file_path=file,
            content_path=str(archivo_md),
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

        session.add(module)
        session.commit()

    contenido_panel = Group(
        f"[bold cyan]✔ Módulo [bold]{name}[/bold] documentado[/bold cyan]",
        f"[bold dim]Archivo fuente: {file}[/bold dim]",
        f"[bold dim]Documentación: {archivo_md}[/bold dim]",
    )

    console.print(Panel(
        contenido_panel,
        title="Módulo registrado",
        border_style="green",
    ))