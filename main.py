from dotenv import load_dotenv
load_dotenv()

import typer
from rich.console import Console
from rich.panel import Panel
from aicli.commands import status, init, module, task, claude_cmd, snapshot
from aicli.db import init_db

init_db()

app = typer.Typer(help="AICLI — Motor de contexto inteligente para Claude Code")
app.add_typer(status.app, name="status")
app.add_typer(init.app, name="init")
app.add_typer(module.app, name="module")
app.add_typer(task.app, name="task")
app.add_typer(claude_cmd.app, name="claude")
app.add_typer(snapshot.app, name="snapshot")

console = Console()


@app.command()
def hello(
    nombre: str = typer.Argument(..., help="Tu nombre"),
    mayusculas: bool = typer.Option(False, "--mayusculas", "-m", help="Mostrar en mayusculas"),
):
    """Saluda al usuario. Comando de ejemplo para aprender Typer."""
    saludo = f"Hola, {nombre} nunca te rindas en la vida!"
    if mayusculas:
        saludo = saludo.upper()
    console.print(Panel(saludo, title="Saludo", border_style="blue"))


@app.command()
def bienvenido(
    nombre: str = typer.Argument(False, help="Tu nombre"),
    colombia: bool = typer.Option(False, "--colombia", "-co", help="Mostrar en Colombia"),
):
    mensaje = f"Hola, bienvenido a mi CLI de prueba {nombre}"
    if colombia:
        mensaje = f"Bienvenido a mi CLI de pruebas {nombre} que bacano tenerte por aqui"
    console.print(Panel(mensaje, title="Mensaje de bienvenida", border_style="red"))


if __name__ == "__main__":
    app()