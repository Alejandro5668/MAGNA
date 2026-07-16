import typer
import time
from rich.console import Console, Group
from rich.panel import Panel
from pathlib import Path
from datetime import datetime
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project, Module
from aicli.services.indexer import analyze_file_deep, module_needs_update, _write_md_atomic
from aicli.tui.theme import magna_error, magna_status, ACCENT, SECTION

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def archive(
    source: str = typer.Argument(..., help="Ruta del archivo (ej: pagos/PagosController.php)"),
):
    """Analiza y documenta un archivo individual en profundidad."""
    from aicli.services.activity import log_activity
    log_activity("archive", source)
    path = Path.cwd()

    with Session(engine) as session:
        project = session.exec(select(Project).where(Project.path == str(path))).first()

    if not project:
        magna_error(console, "Este directorio no está registrado. Ejecutá ctx init primero.")
        raise typer.Exit(code=1)

    source_file = path / source
    if not source_file.exists():
        magna_error(console, f"No se encontró {source}")
        raise typer.Exit(code=1)

    with Session(engine) as session:
        existing_module = session.exec(
            select(Module).where(Module.file_path == source, Module.project_id == project.id)
        ).first()

    if existing_module and not module_needs_update(source, path, existing_module):
        console.print(Panel(
            f"[{ACCENT}][bold]{source}[/bold] ya está al día — sin cambios desde la última documentación.[/{ACCENT}]",
            title="Sin cambios",
            border_style=ACCENT,
        ))
        return

    with magna_status(console, f"Analizando {source}..."):
        content_md, tokens = analyze_file_deep(path, source, project.name, project.stack or "desconocido")

    base = Path.home() / ".mycontext" / "projects" / str(project.id)
    md_file = base / Path(source).with_suffix(".md")
    md_file.parent.mkdir(parents=True, exist_ok=True)
    _write_md_atomic(md_file, content_md)

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
            f"[bold #4ADE80]✔ {source}[/bold #4ADE80]",
            f"[{SECTION}]Doc: {md_file}[/{SECTION}]",
            f"[{SECTION}]Tokens: {tokens:,}[/{SECTION}]",
        ),
        title=title,
        border_style="#4ADE80",
    ))