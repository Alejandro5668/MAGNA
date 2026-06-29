import typer
from rich.console import Console, Group
from rich.panel import Panel
from pathlib import Path
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project, Module
from aicli.services.indexer import get_tree, generate_project_md

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def proyecto():
    """Genera PROYECTO.md con conocimiento estructural del proyecto activo."""
    path = Path.cwd()

    with Session(engine) as session:
        p = session.exec(select(Project).where(Project.path == str(path))).first()

    if not p:
        console.print("[bold red]Error:[/bold red] Este directorio no está registrado. Ejecutá [bold]ctx init[/bold] primero.")
        raise typer.Exit(code=1)

    with Session(engine) as session:
        modules_db = list(session.exec(select(Module).where(Module.project_id == p.id)).all())

    if not modules_db:
        console.print("[bold yellow]Aviso:[/bold yellow] No hay módulos documentados. Ejecutá [bold]ctx init[/bold] primero.")
        raise typer.Exit(code=1)

    modules = [
        {"name": m.name, "file_path": m.file_path, "description": m.description or ""}
        for m in modules_db
    ]

    dest = Path.home() / ".mycontext" / "projects" / str(p.id) / "PROYECTO.md"

    console.print(f"\n[bold cyan]Generando PROYECTO.md para {p.name}...[/bold cyan]")
    console.print(f"  [dim]{len(modules)} módulos documentados como base[/dim]")

    def on_progreso(msg: str) -> None:
        console.print(f"  [bold green]✔[/bold green] [dim]{msg}[/dim]")

    with console.status("Analizando proyecto y generando conocimiento estructural...", spinner="dots3", spinner_style="cyan"):
        tree = get_tree(path)
        content, tokens = generate_project_md(
            path, p.name, p.stack or "desconocido", tree, modules, on_progreso=on_progreso
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")

    console.print(Panel(
        Group(
            f"[bold cyan]✔ PROYECTO.md generado para {p.name}[/bold cyan]",
            f"[bold dim]Tokens: {tokens:,}[/bold dim]",
            "",
            "[dim]Las secciones marcadas como 'pendiente' podés enriquecerlas con tu conocimiento del proyecto.[/dim]",
            f"[dim]Ubicación: {dest}[/dim]",
        ),
        title="ctx proyecto",
        border_style="green"
    ))