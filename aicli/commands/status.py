import typer
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project, Module
from aicli.tui.theme import magna_warn, magna_info, ACCENT, SECTION, BORDER

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def status():
    """Muestra la arquitectura documentada del proyecto agrupada por carpeta."""
    path = Path.cwd()

    with Session(engine) as session:
        project = session.exec(select(Project).where(Project.path == str(path))).first()

    if not project:
        magna_warn(console, "Este directorio no está registrado. Ejecutá ctx init primero.")
        return

    with Session(engine) as session:
        modules = list(session.exec(select(Module).where(Module.project_id == project.id)).all())

    if not modules:
        console.print(Panel(
            f"[{SECTION}]Todavía no hay módulos documentados.[/{SECTION}]\n\n"
            f"Ejecutá [bold {ACCENT}]ctx init[/bold {ACCENT}] para mapear la arquitectura del proyecto.",
            title="Sin documentación",
            border_style=ACCENT,
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

    table = Table(style=ACCENT, show_header=True, header_style=f"bold {ACCENT}")
    table.add_column("Carpeta", style="bold", min_width=22)
    table.add_column("Módulos", justify="right", style=SECTION)
    table.add_column("Última doc", style=SECTION)

    for folder, mods in sorted_folders:
        ts = _last_updated(mods)
        date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "—"
        table.add_row(f"{folder}/", str(len(mods)), date)

    console.print()
    console.print(Panel(
        table,
        title=f"[bold {ACCENT}]Arquitectura documentada — {project.name}[/bold {ACCENT}]",
        border_style=ACCENT,
    ))
    magna_info(console, f"{len(modules)} módulos en {len(folders)} carpetas")
    console.print()
    magna_info(console, f"¿No ves una carpeta? Ejecutá ctx init para actualizar la arquitectura.")

    rules_dir = Path.home() / ".mycontext" / "rules"
    rule_files = sorted(rules_dir.glob("*.md")) if rules_dir.exists() else []
    if rule_files:
        names = ", ".join(f.name for f in rule_files)
        magna_info(console, f"Reglas del equipo: {len(rule_files)} archivo/s ({names})")
    else:
        magna_info(console, "Reglas del equipo: ninguna")
