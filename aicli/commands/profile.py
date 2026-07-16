import typer
import os
import subprocess
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project
from aicli.services.stack_profile import get_profile
from aicli.services.indexer import get_tree, generate_role_md, _write_md_atomic
from aicli.tui.theme import magna_ok, magna_warn, magna_info, magna_error, ACCENT, SECTION, BORDER

app = typer.Typer()
console = Console()

_ROL_PATH = Path.home() / ".mycontext" / "rol.md"


@app.callback(invoke_without_command=True)
def profile(
    regenerar: bool = typer.Option(False, "--regenerar", "-r", help="Regenera rol.md con IA desde el código real."),
    editar: bool = typer.Option(False, "--editar", "-e", help="Abre rol.md en el editor del sistema."),
):
    """Muestra el perfil de stack detectado y gestiona rol.md."""
    path = Path.cwd()

    with Session(engine) as session:
        project = session.exec(select(Project).where(Project.path == str(path))).first()

    if not project:
        magna_warn(console, "Este directorio no está registrado. Ejecutá ctx init primero.")
        return

    profile_obj = get_profile(project.stack or "desconocido")

    # --- tabla de perfil ---
    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column(style=f"bold {SECTION}")
    table.add_column(style="white")
    table.add_row("Stack detectado", project.stack or "desconocido")
    table.add_row("Perfil activo", profile_obj.name)
    table.add_row("Encoding", profile_obj.encoding)
    table.add_row("rol.md", str(_ROL_PATH))

    console.print(Panel(table, title=f"[bold {ACCENT}]{project.name}[/bold {ACCENT}]", border_style=BORDER))

    # --- preview de hints ---
    if profile_obj.hints:
        console.print(Panel(
            profile_obj.hints,
            title=f"[{SECTION}]Hints del perfil[/{SECTION}]",
            border_style=BORDER,
        ))

    # --- preview de rol.md ---
    if _ROL_PATH.exists():
        preview = _ROL_PATH.read_text(encoding="utf-8")
        lines = preview.splitlines()
        shown = "\n".join(lines[:20])
        suffix = f"\n[dim]… ({len(lines) - 20} líneas más)[/dim]" if len(lines) > 20 else ""
        console.print(Panel(
            shown + suffix,
            title=f"[{SECTION}]rol.md[/{SECTION}]",
            border_style=BORDER,
        ))
    else:
        magna_warn(console, "rol.md no existe todavía — se creará en el próximo ctx init.")

    # --- acciones ---
    if regenerar:
        magna_info(console, "Regenerando rol.md con IA...")
        tree = get_tree(path)
        content = generate_role_md(
            path, project.name, project.stack or "desconocido",
            tree, fallback=profile_obj.role_template, encoding=profile_obj.encoding,
        )
        _write_md_atomic(_ROL_PATH, content)
        magna_ok(console, f"rol.md regenerado — {len(content.splitlines())} líneas")

    if editar:
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
        if editor:
            subprocess.run([editor, str(_ROL_PATH)])
        else:
            # Windows: abre con el programa predeterminado
            os.startfile(str(_ROL_PATH))
