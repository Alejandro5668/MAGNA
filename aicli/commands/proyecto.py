import typer
from pathlib import Path
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project, Module
from aicli.services.indexer import get_tree, generate_project_md
from aicli.services.stack_profile import get_profile
from aicli.tui.theme import print_header, print_footer, magna_status, magna_ok, magna_info, magna_error, magna_panel
from rich.console import Console

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def proyecto():  # registered as "scan" in main.py
    """Genera PROYECTO.md con conocimiento estructural del proyecto activo."""
    from aicli.services.activity import log_activity
    log_activity("scan")
    path = Path.cwd()

    with Session(engine) as session:
        p = session.exec(select(Project).where(Project.path == str(path))).first()

    if not p:
        magna_error(console, "Directorio no registrado. Ejecutá ctx init primero.")
        raise typer.Exit(code=1)

    with Session(engine) as session:
        modules_db = list(session.exec(select(Module).where(Module.project_id == p.id)).all())

    if not modules_db:
        magna_error(console, "Sin módulos documentados. Ejecutá ctx init primero.")
        raise typer.Exit(code=1)

    modules = [
        {"name": m.name, "file_path": m.file_path, "description": m.description or ""}
        for m in modules_db
    ]

    dest = Path.home() / ".mycontext" / "projects" / str(p.id) / "PROYECTO.md"

    print_header(console, "ctx scan", "Detectando patrones del proyecto")
    magna_info(console, f"{len(modules)} módulos documentados como base")

    def on_progreso(msg: str) -> None:
        magna_ok(console, msg)

    with magna_status(console, "Analizando estructura y generando conocimiento..."):
        tree = get_tree(path)
        content, tokens = generate_project_md(
            path, p.name, p.stack or "desconocido", tree, modules,
            on_progreso=on_progreso,
            encoding=get_profile(p.stack or "desconocido").encoding,
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")

    magna_ok(console, f"PROYECTO.md generado  ·  {tokens:,} tokens")
    magna_info(console, f"Ubicación: {dest}")
    print_footer(console)
