import typer
import time
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlmodel import Session, select, func
from aicli.db import engine
from aicli.services.indexer import leer_archivos_clave, analizar_con_claude
from pathlib import Path
from aicli.services.indexer import obtener_arbol

from aicli.db.models import Project

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

        tabla.add_row("commands", "comandos de la CLI")
        tabla.add_row("db", "Modelos y conexion SQLite")
        tabla.add_row("services", "Logica de negocio")

    console.print(tabla)

    arbol = obtener_arbol(Path.cwd())
    for f in arbol:
        print(f)

    contenido = leer_archivos_clave(Path.cwd(), arbol)
    print(contenido)

    modulos = analizar_con_claude("AICLI", "python", arbol, contenido)
    for m in modulos:
        print(m)


