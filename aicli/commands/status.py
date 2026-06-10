import typer
import time
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlmodel import Session, select, func
from aicli.db import engine
from aicli.db.models import Project, Module

app = typer.Typer() # con esta linea de codigo se crea la CLI, tiene que ir en cada archivo .py
console = Console()

# esto le dice a la app que ejecute este archivo por completo y no un subcomando
@app.callback(invoke_without_command=True)
def status():
    console.print("[bold cyan]Estado del contexto[/bold cyan]")

    with Session(engine) as session:
        statement = select(func.count()).select_from(Project)
        total = session.exec(statement).first()
        contenido = f"[bold]Modulos documentados: [/bold] [dim]0[/dim]\n[bold]Proyectos registrados[/bold]: [dim]{total}[/dim]"


    console.print(Panel(contenido, title="AICLI - ESTADO DEL CONTEXTO", border_style="cyan"))

    with console.status("Consultando modulos...", spinner="dots3", spinner_style="cyan"):
        time.sleep(1)
        tabla = Table(title="Modulos", style="cyan")

        tabla.add_column("nombre", style="bold")
        tabla.add_column("Descripción")

        with Session(engine) as session:
            modules = select(Module.name, Module.description)
            results = session.exec(modules).all()

            # Si no hay resultados ...
            if not results:
                console.print("[yellow]No hay módulos registrados.[/yellow]")
                raise typer.Exit()

            for m in results:
                tabla.add_row(m.name, m.description)

    console.print(tabla)


