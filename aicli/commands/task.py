import typer
import json
import os
import anthropic
from typing import Annotated, Optional
from rich.console import Console
from pathlib import Path
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project, Module
from aicli.services.builder import build_context
from aicli.services.caller import launch_claude
from aicli.services.indexer import describe_image
from aicli.tui.theme import magna_status, magna_ok, magna_warn, magna_error, magna_info, magna_panel, magna_task_plan, ACCENT, SECTION

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
    ticket_id: str | None = None,
    jira_data: dict | None = None,
    suspend_fn=None,
) -> None:
    path = Path.cwd()

    from aicli.services.activity import log_activity
    log_activity("task", task_desc[:60] if task_desc else None)

    with Session(engine) as session:
        project = session.exec(select(Project).where(Project.path == str(path))).first()

    if not project:
        magna_error(console, "Este directorio no está registrado. Ejecutá ctx init primero.")
        return

    if ticket_id:
        from aicli.services.tickets import save_active_ticket
        save_active_ticket(ticket_id.upper(), "")

    with Session(engine) as session:
        modules = list(session.exec(select(Module).where(Module.project_id == project.id)).all())

    if not modules:
        magna_warn(console, "No hay módulos documentados. Ejecutá ctx init primero.")
        return

    if file:
        magna_info(console, f"Archivo: {file}")

    with magna_status(console, "Analizando tarea..."):
        relevant = _detect_relevant_modules(task_desc, modules, file)

    if not relevant:
        relevant = modules

    if file:
        file_module = next((m for m in modules if m.file_path == file), None)
        if file_module and file_module not in relevant:
            relevant = [file_module] + relevant

    with magna_status(console, "Generando plan de implementación..."):
        brief = _generate_task_brief(task_desc, relevant, file)

    magna_task_plan(console, relevant, brief)

    image_description = None
    if image:
        image_path = Path(image)
        if not image_path.exists():
            magna_warn(console, f"Imagen no encontrada: {image} — se omite")
        else:
            with magna_status(console, "Analizando imagen..."):
                try:
                    image_description, tokens_img = describe_image(image)
                    magna_ok(console, f"Imagen analizada · {tokens_img:,} tokens")
                except Exception as e:
                    magna_warn(console, f"No se pudo analizar la imagen: {e}")

    # ── Adjuntos de Jira ───────────────────────────────────────────────────────
    jira_images: list[tuple[str, str]] = []
    if jira_data and jira_data.get("attachments"):
        from aicli.services.jira import download_image_attachments
        with magna_status(console, "Descargando adjuntos de Jira..."):
            local_paths = download_image_attachments(jira_data["attachments"])
        if local_paths:
            magna_ok(console, f"{len(local_paths)} imagen(es) descargada(s) de Jira")
        for img_path in local_paths:
            name = Path(img_path).name
            with magna_status(console, f"Analizando {name}..."):
                try:
                    desc, tokens_j = describe_image(img_path)
                    jira_images.append((name, desc))
                    magna_ok(console, f"{name} · {tokens_j:,} tokens")
                except Exception as e:
                    magna_warn(console, f"No se pudo analizar {name}: {e}")

        non_image = [
            a for a in jira_data["attachments"]
            if not a.get("mimeType", "").startswith("image/")
        ]
        if non_image:
            magna_info(console, f"{len(non_image)} adjunto(s) no-imagen incluido(s) como metadata")

    context = build_context(relevant)
    if suspend_fn:
        suspend_fn(lambda: launch_claude(
            context, task_desc, brief, file, image_description,
            ticket_history, ticket_id, jira_data, jira_images,
        ))
    else:
        launch_claude(
            context, task_desc, brief, file, image_description,
            ticket_history, ticket_id, jira_data, jira_images,
        )


@app.callback(invoke_without_command=True)
def task(
    task_text: str = typer.Argument(..., help="Descripción de la tarea a realizar"),
    archivo: Annotated[Optional[str], typer.Option("--archivo", "-f", help="Ruta del archivo donde ocurre el problema")] = None,
    image: Annotated[Optional[str], typer.Option("--imagen", "-i", help="Ruta de imagen de referencia (screenshot, mockup)")] = None,
):
    """Detecta módulos relevantes para la tarea y lanza Claude con contexto y plan."""
    _execute_task(task_text, archivo, image)
