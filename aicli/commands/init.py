import typer
from rich.console import Console
from pathlib import Path
from datetime import datetime
from rich.panel import Panel
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project

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
        path=path,
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

    console.print(f"[bold cyan]:) Proyecto [bold]{name}[/bold] registrado [/bold cyan]")
    console.print(f"[bold dim]Stack: {stack}[/bold dim]")
    console.print(f"[bold dim]Ruta: {path}[/bold dim]")