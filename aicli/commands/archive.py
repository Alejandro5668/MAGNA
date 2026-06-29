import typer
import time
from rich.console import Console, Group
from rich.panel import Panel
from pathlib import Path
from datetime import datetime
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project, Module
from aicli.services.indexer import analyze_file_deep, module_needs_update

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def archive(
    source: str = typer.Argument(..., help="Ruta del archivo (ej: pagos/PagosController.php)"),
):
    """Analiza y documenta un archivo individual en profundidad."""
    path = Path.cwd()

    with Session(engine) as session:
        project = session.exec(select(Project).where(Project.path == str(path))).first()

    if not project:
        console.print("[bold red]Error:[/bold red] Este directorio no está registrado. Ejecutá [bold]ctx init[/bold] primero.")
        raise typer.Exit(code=1)

    source_file = path / source
    if not source_file.exists():
        console.print(f"[bold red]Error:[/bold red] No se encontró [bold]{source}[/bold]")
        raise typer.Exit(code=1)

    with Session(engine) as session:
        existing_module = session.exec(
            select(Module).where(Module.file_path == source, Module.project_id == project.id)
        ).first()

    if existing_module and not module_needs_update(source, path, existing_module):
        console.print(Panel(
            f"[cyan][bold]{source}[/bold] ya está al día — sin cambios desde la última documentación.[/cyan]",
            title="Sin cambios",
            border_style="yellow"
        ))
        return

    with console.status(f"[bold cyan]Analizando {source}...[/bold cyan]", spinner="dots3", spinner_style="cyan"):
        content_md, tokens = analyze_file_deep(path, source, project.name, project.stack or "desconocido")

    base = Path.home() / ".mycontext" / "projects" / str(project.id)
    md_file = base / Path(source).with_suffix(".md")
    md_file.parent.mkdir(parents=True, exist_ok=True)
    md_file.write_text(content_md, encoding="utf-8")

    name = Path(source).stem
    description = next((l.lstrip("# ") for l in content_md.splitlines() if l.strip()), name)

    with Session(engine) as session:
        if existing_module:
            m = session.get(Module, existing_module.id)
            m.content_path = str(md_file)
            m.last_updated_at = time.time()
            session.add(m)
            session.commit()
            title = "Archivo actualizado"
        else:
            module = Module(
                project_id=project.id,
                name=name,
                description=description,
                file_path=source,
                content_path=str(md_file),
                created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                last_updated_at=time.time(),
            )
            session.add(module)
            session.commit()
            title = "Archivo documentado"

    console.print(Panel(
        Group(
            f"[bold cyan]✔ {source}[/bold cyan]",
            f"[bold dim]Doc: {md_file}[/bold dim]",
            f"[bold dim]Tokens: {tokens:,}[/bold dim]",
        ),
        title=title,
        border_style="green"
    ))