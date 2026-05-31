import typer
import time
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer() # con esta linea de codigo se crea la CLI, tiene que ir en cada archivo .py
console = Console()

# esto le dice a la app que ejecute este archivo por completo y no un subcomando
@app.callback(invoke_without_command=True)
def status():
    console.print("[bold green]Estado del contexto[/bold green]")
    contenido = "[bold]Modulos documentados: [/bold] [dim]0[/dim]\n[bold]Proyectos registrados[/bold]: [dim]0[/dim]"
    console.print(Panel(contenido, title="AICLI - ESTADO DEL CONTEXTO", border_style="blue"))

with console.status("Consultando modulos...", spinner="dots3"):
    time.sleep(1)
    tabla = Table(title="Modulos")

    tabla.add_column("nombre", style="bold")
    tabla.add_column("Descripción")

    tabla.add_row("commands", "comandos de la CLI")
    tabla.add_row("db", "Modelos y conexion SQLite")
    tabla.add_row("services", "Logica de negocio")

console.print(tabla)


