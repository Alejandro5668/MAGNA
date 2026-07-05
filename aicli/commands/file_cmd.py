import typer
import time
from rich.console import Console, Group
from rich.panel import Panel
from pathlib import Path
from datetime import datetime
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project, Module
from aicli.services.indexer import document_zone, NON_CODE_EXTENSIONS
from aicli.tui.theme import magna_ok, magna_warn, magna_error, magna_info, magna_status, ACCENT, SECTION

app = typer.Typer()
console = Console()


def _save_zone_modules(modules: list[dict], project: Project) -> None:
    base = Path.home() / ".mycontext" / "projects" / str(project.id)
    with Session(engine) as session:
        for m in modules:
            md_file = base / Path(m["file_path"]).with_suffix(".md")
            md_file.parent.mkdir(parents=True, exist_ok=True)
            md_file.write_text(m.get("documentation", ""), encoding="utf-8")

            existing = session.exec(
                select(Module).where(
                    Module.file_path == m["file_path"],
                    Module.project_id == project.id
                )
            ).first()

            if existing:
                existing.content_path = str(md_file)
                existing.last_updated_at = time.time()
                existing.description = m.get("description", existing.description)
                session.add(existing)
            else:
                session.add(Module(
                    project_id=project.id,
                    name=m["name"],
                    description=m.get("description", ""),
                    file_path=m["file_path"],
                    content_path=str(md_file),
                    created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    last_updated_at=time.time(),
                    category=m.get("category"),
                    domain=m.get("domain"),
                ))
        session.commit()


@app.callback(invoke_without_command=True)
def file_cmd(
    folder: str = typer.Argument(..., help="Carpeta a documentar (ej: pagos o controllers/pagos)"),
):
    """Documenta en profundidad una carpeta/zona específica del proyecto."""
    path = Path.cwd()

    with Session(engine) as session:
        project = session.exec(select(Project).where(Project.path == str(path))).first()

    if not project:
        magna_error(console, "Este directorio no está registrado. Ejecutá ctx init primero.")
        return

    zone_path = path / folder
    if not zone_path.is_dir():
        if zone_path.is_file() or Path(folder).suffix:
            magna_warn(
                console,
                f"{folder} es un archivo, no una carpeta. "
                f"Para documentar un archivo individual usá ctx archive."
            )
            return
        matches = sorted(
            [d for d in path.rglob(folder) if d.is_dir()],
            key=lambda d: len(d.parts)
        )
        if not matches:
            magna_warn(console, f"No se encontró la carpeta {folder}. Verificá el nombre e intentá de nuevo.")
            return
        zone_path = matches[0]

    n_files = len([
        f for f in zone_path.rglob("*")
        if f.is_file() and f.suffix not in NON_CODE_EXTENSIONS
    ])

    console.print(f"\n[bold {ACCENT}]Documentando zona '{folder}' en {project.name}...[/bold {ACCENT}]")
    magna_info(console, f"{n_files:,} archivos de código en esta zona")

    def on_progreso(msg: str) -> None:
        magna_ok(console, msg)

    try:
        with magna_status(console, f"Analizando zona '{folder}'..."):
            modules = document_zone(
                path, zone_path, project.stack or "desconocido", on_progreso=on_progreso
            )
    except Exception as e:
        magna_error(console, f"No se pudo documentar la zona — {e}")
        magna_info(console, "Intentá con una zona más pequeña o usá ctx archive para archivos individuales.")
        return

    if not modules:
        magna_warn(console, "No se identificaron componentes en esta zona.")
        return

    _save_zone_modules(modules, project)

    console.print(Panel(
        Group(
            f"[bold #4ADE80]✔ {folder} — {len(modules)} componentes documentados[/bold #4ADE80]",
            f"[{SECTION}]Proyecto: {project.name}[/{SECTION}]",
        ),
        title="ctx file",
        border_style="#4ADE80",
    ))
