import typer
import json
import os
import anthropic
from typing import Annotated, Optional
from rich.console import Console
from rich.panel import Panel
from pathlib import Path
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project, Module
from aicli.services.builder import build_context
from aicli.services.caller import launch_claude
from aicli.services.indexer import describe_image

app = typer.Typer()
console = Console()


def _detect_relevant_modules(
    task_desc: str, modules: list[Module], file: str | None = None
) -> list[Module]:
    listing = "\n".join([
        f"- {m.name}: {m.description} | archivo: {m.file_path}"
        for m in modules
    ])

    file_context = (
        f"\nEl desarrollador indica que el problema ocurre específicamente en: {file}"
        if file else ""
    )

    prompt = f"""Tenés que identificar qué módulos de un proyecto de software son relevantes
para una tarea específica de desarrollo.

Tarea del desarrollador: {task_desc}{file_context}

Módulos disponibles en el proyecto:
{listing}

Analizá la tarea, entendé qué partes del sistema necesita tocar, y devolvé ÚNICAMENTE
un JSON con los nombres de los módulos relevantes, sin texto adicional:
["nombre_modulo_1", "nombre_modulo_2"]

Seleccioná solo los módulos que realmente necesitarán ser leídos o modificados.
Si no podés filtrar con seguridad, devolvé todos los nombres."""

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        thinking={"type": "enabled", "budget_tokens": 2000},
        messages=[{"role": "user", "content": prompt}]
    )

    text = next(b.text for b in response.content if b.type == "text")
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    names = json.loads(text)
    return [m for m in modules if m.name in names]


def _generate_task_brief(
    task_desc: str, modules: list[Module], file: str | None = None
) -> str:
    listing = "\n".join([f"- {m.name} ({m.file_path}): {m.description}" for m in modules])

    file_context = (
        f"\nPunto de entrada específico donde ocurre el problema: {file}"
        if file else ""
    )

    prompt = f"""Sos un arquitecto de software senior. Un desarrollador va a trabajar en esta
tarea con Claude Code como asistente.

Tarea: {task_desc}{file_context}

Módulos del proyecto involucrados:
{listing}

Generá un plan técnico conciso de máximo 8 líneas que indique:
- Qué hay que revisar o cambiar, empezando por el archivo específico si se indicó uno
- En qué orden hacerlo
- Qué dependencias o efectos secundarios tener en cuenta

El plan va a ser la primera cosa que lea Claude Code antes de empezar. Sé específico
y técnico. Solo el plan, sin introducción ni conclusión."""

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


def _execute_task(
    task_desc: str,
    file: str | None = None,
    image: str | None = None,
    ticket_history: str | None = None,
) -> None:
    path = Path.cwd()

    with Session(engine) as session:
        project = session.exec(select(Project).where(Project.path == str(path))).first()

    if not project:
        console.print("[bold red]Error:[/bold red] Este directorio no está registrado. Ejecutá [bold]ctx init[/bold] primero.")
        return

    with Session(engine) as session:
        modules = list(session.exec(select(Module).where(Module.project_id == project.id)).all())

    if not modules:
        console.print("[bold yellow]Aviso:[/bold yellow] No hay módulos documentados. Ejecutá [bold]ctx init[/bold] primero.")
        return

    if file:
        console.print(f"[bold cyan]Archivo:[/bold cyan] [dim]{file}[/dim]")

    with console.status("Analizando tarea...", spinner="dots3", spinner_style="cyan"):
        relevant = _detect_relevant_modules(task_desc, modules, file)

    if not relevant:
        relevant = modules

    if file:
        file_module = next((m for m in modules if m.file_path == file), None)
        if file_module and file_module not in relevant:
            relevant = [file_module] + relevant

    with console.status("Generando plan de implementación...", spinner="dots3", spinner_style="cyan"):
        brief = _generate_task_brief(task_desc, relevant, file)

    names = ", ".join(m.name for m in relevant)
    console.print(f"[bold cyan]Módulos seleccionados:[/bold cyan] [dim]{names}[/dim]")
    console.print(Panel(brief, title="Plan de implementación", border_style="cyan"))

    image_description = None
    if image:
        image_path = Path(image)
        if not image_path.exists():
            console.print(f"[bold yellow]⚠[/bold yellow] [dim]Imagen no encontrada: {image} — se omite[/dim]")
        else:
            with console.status("Analizando imagen...", spinner="dots3", spinner_style="cyan"):
                try:
                    image_description, tokens_img = describe_image(image)
                    console.print(f"  [bold green]✔[/bold green] [dim]Imagen analizada · {tokens_img:,} tokens[/dim]")
                except Exception as e:
                    console.print(f"[bold yellow]⚠[/bold yellow] [dim]No se pudo analizar la imagen: {e}[/dim]")

    context = build_context(relevant)
    launch_claude(context, task_desc, brief, file, image_description, ticket_history)


@app.callback(invoke_without_command=True)
def task(
    task_text: str = typer.Argument(..., help="Descripción de la tarea a realizar"),
    archivo: Annotated[Optional[str], typer.Option("--archivo", "-f", help="Ruta del archivo donde ocurre el problema")] = None,
    image: Annotated[Optional[str], typer.Option("--imagen", "-i", help="Ruta de imagen de referencia (screenshot, mockup)")] = None,
):
    """Detecta módulos relevantes para la tarea y lanza Claude con contexto y plan."""
    _execute_task(task_text, archivo, image)
