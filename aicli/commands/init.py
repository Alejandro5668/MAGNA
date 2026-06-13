import typer
from rich.console import Console, Group
from pathlib import Path
from datetime import datetime
from rich.panel import Panel
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project
from aicli.services.indexer import indexar_proyecto
from aicli.db.models import Module

app = typer.Typer()
console = Console()

def detectar_stack(path: Path) -> str:
    if (path / "requirements.txt").exists():
        return "python"
    if (path / "composer.json").exists():
        return "laravel"
    if (path / "pom.xml").exists():
        return "java"
    return "desconocido"

@app.callback(invoke_without_command=True)
def init():
    path = Path.cwd()
    name = path.name
    stack = detectar_stack(path)

    proyecto = Project(
        name=name,
        path=str(path),
        stack=stack,
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    with Session(engine) as session:
        # Convertimos a string el path ya que asi la comparacion con la columna es compatible se hace str vs str
        statement = select(Project).where(Project.path == str(path))
        exist = session.exec(statement).first()
        if (exist):
            mensaje = f"{path} ya existe"
            console.print(Panel(mensaje, title="Error", border_style="red"))
            raise typer.Exit(code=1)

        session.add(proyecto)
        session.commit()
        session.refresh(proyecto)

    with console.status("Analizando proyecto...", spinner="dots3", spinner_style="cyan"):
        modulos = indexar_proyecto(path, name, stack)

        directorio = Path.home() / ".mycontext" / "projects" / str(proyecto.id)
        directorio.mkdir(parents=True, exist_ok=True)

        for m in modulos:
            archivo_md = directorio / f"{m['name']}"
            archivo_md.write_text(m["content_md"], encoding="utf-8")
            m["content_path"] = str(archivo_md)

    with Session(engine) as session:
        for m in modulos:
            modulo = Module(
                project_id = proyecto.id,
                name = m["name"],
                description = m["description"],
                file_path = m["file_path"],
                content_path = m["content_path"],
                created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            session.add(modulo)
            session.commit()

    contenido_panel = Group(
        f"[bold cyan]✔ Proyecto [bold]{name}[/bold] registrado [/bold cyan]",
        f"[bold dim]Stack: {stack}[/bold dim]",
        f"[bold dim]Ruta: {path}[/bold dim]"
    )

    console.print(
        Panel(
            contenido_panel,
            title="Registro Exitoso",
            border_style="green"
        )
    )