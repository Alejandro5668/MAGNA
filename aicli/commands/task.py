import typer
import json
import logging
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
from aicli.services.indexer import describe_image, MODEL_BY_OPERATION
from aicli.tui.theme import magna_status, magna_ok, magna_warn, magna_error, magna_info, magna_panel, magna_task_plan, ACCENT, SECTION

app = typer.Typer()
console = Console()


def _detect_relevant_modules(
    task_desc: str, modules: list[Module], file: str | None = None, project_context: str | None = None
) -> list[Module]:
    listing_parts = []
    for m in modules:
        listing_parts.append(f"- {m.name}: {m.description} | archivo: {m.file_path}")
        if m.content_path:
            md_path = Path(m.content_path)
            if md_path.exists():
                snippet = md_path.read_text(encoding="utf-8", errors="replace")[:300].replace("\n", " ")
                listing_parts.append(f"  Contexto: {snippet}")
    listing = "\n".join(listing_parts)

    file_context = (
        f"\nEl desarrollador indica que el problema ocurre específicamente en: {file}"
        if file else ""
    )

    project_ctx_block = f"\nContexto del proyecto (convenciones, arquitectura, patrones):\n{project_context}\n" if project_context else ""

    prompt = f"""Tenés que identificar qué módulos de un proyecto de software son relevantes
para una tarea específica de desarrollo.

Tarea del desarrollador: {task_desc}{file_context}
{project_ctx_block}
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
    names, _ = json.JSONDecoder().raw_decode(text)
    return [m for m in modules if m.name in names]


def _generate_task_brief(
    task_desc: str, modules: list[Module], file: str | None = None, evidence: str | None = None
) -> str:
    listing = "\n".join([f"- {m.name} ({m.file_path}): {m.description}" for m in modules])

    file_context = (
        f"\nPunto de entrada específico donde ocurre el problema: {file}"
        if file else ""
    )

    evidence_block = f"\nEvidencia disponible (imágenes/video/Excel ya analizados):\n{evidence}\n" if evidence else ""

    prompt = f"""Sos un arquitecto de software senior. Un desarrollador va a trabajar en esta
tarea con Claude Code como asistente.

Tarea: {task_desc}{file_context}

Módulos del proyecto involucrados:
{listing}
{evidence_block}
Generá un plan técnico conciso de máximo 8 líneas que indique:
- Qué hay que revisar o cambiar, empezando por el archivo específico si se indicó uno
- En qué orden hacerlo
- Qué dependencias o efectos secundarios tener en cuenta
- Si hay evidencia disponible, básate en ella para ser específico sobre el bug o comportamiento a resolver

El plan va a ser la primera cosa que lea Claude Code antes de empezar. Sé específico
y técnico. Solo el plan, sin introducción ni conclusión."""

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=MODEL_BY_OPERATION["task_brief"],
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

    project_context = None
    if modules:
        proyecto_md_path = Path.home() / ".mycontext" / "projects" / str(modules[0].project_id) / "PROYECTO.md"
        if proyecto_md_path.exists():
            project_context = proyecto_md_path.read_text(encoding="utf-8", errors="replace")

    with magna_status(console, "Analizando tarea..."):
        relevant = _detect_relevant_modules(task_desc, modules, file, project_context)

    if not relevant:
        relevant = modules

    if file:
        file_module = next((m for m in modules if m.file_path == file), None)
        if file_module and file_module not in relevant:
            relevant = [file_module] + relevant

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
    jira_excel:  list[tuple[str, str]] = []
    jira_videos: list[tuple[str, str]] = []
    if jira_data and jira_data.get("attachments"):
        from aicli.services.jira import (
            download_image_attachments, download_excel_attachments,
            download_video_attachments, excel_to_text, _EXCEL_MIME, _VIDEO_MIME,
        )
        from aicli.services.tickets import get_jira_cache, save_processed_attachments

        attachments = jira_data["attachments"]
        cache = get_jira_cache(ticket_id) if ticket_id else {"processed_attachments": {}}
        processed = cache.get("processed_attachments", {})

        # Hidrata los adjuntos ya procesados en un resume anterior, sin pagar IA de nuevo.
        for cached in processed.values():
            entry = (cached.get("name", ""), cached.get("text", ""))
            cached_type = cached.get("type")
            if cached_type == "image":
                jira_images.append(entry)
            elif cached_type == "excel":
                jira_excel.append(entry)
            elif cached_type == "video":
                jira_videos.append(entry)

        pending = [a for a in attachments if str(a.get("id")) not in processed]
        if pending and len(pending) < len(attachments):
            magna_info(console, f"{len(attachments) - len(pending)} adjunto(s) ya procesado(s) reutilizado(s) del cache")
        elif not pending and processed:
            magna_info(console, f"{len(attachments)} adjunto(s) ya procesado(s) reutilizado(s) del cache")

        id_by_filename = {a.get("filename"): str(a.get("id")) for a in pending if a.get("filename")}
        new_cache_entries: dict[str, dict] = {}

        with magna_status(console, "Descargando adjuntos de Jira..."):
            local_paths = download_image_attachments(pending)
            excel_paths = download_excel_attachments(pending)
            video_paths = download_video_attachments(pending)

        if local_paths:
            magna_ok(console, f"{len(local_paths)} imagen(es) descargada(s) de Jira")
        for img_path in local_paths:
            name = Path(img_path).name
            with magna_status(console, f"Analizando {name}..."):
                try:
                    desc, tokens_j = describe_image(img_path)
                    jira_images.append((name, desc))
                    magna_ok(console, f"{name} · {tokens_j:,} tokens")
                    att_id = id_by_filename.get(name)
                    if att_id:
                        new_cache_entries[att_id] = {"type": "image", "name": name, "text": desc}
                except Exception as e:
                    magna_warn(console, f"No se pudo analizar {name}: {e}")

        if excel_paths:
            magna_ok(console, f"{len(excel_paths)} Excel descargado(s) de Jira")
        for xls_path in excel_paths:
            name = Path(xls_path).name
            with magna_status(console, f"Leyendo {name}..."):
                content = excel_to_text(xls_path)
                jira_excel.append((name, content))
                magna_ok(console, f"{name} convertido a texto")
                att_id = id_by_filename.get(name)
                if att_id:
                    new_cache_entries[att_id] = {"type": "excel", "name": name, "text": content}

        if video_paths:
            if not os.getenv("GEMINI_API_KEY"):
                magna_warn(console, f"{len(video_paths)} video(s) adjunto(s) — configurá GEMINI_API_KEY para analizarlos")
            else:
                magna_ok(console, f"{len(video_paths)} video(s) descargado(s) de Jira")
                from aicli.services.gemini import analyze_video
                for vid_path in video_paths:
                    name = Path(vid_path).name
                    with magna_status(console, f"Analizando {name} con Gemini..."):
                        try:
                            desc, tokens_v = analyze_video(vid_path)
                            jira_videos.append((name, desc))
                            magna_ok(console, f"{name} · {tokens_v:,} tokens")
                            att_id = id_by_filename.get(name)
                            if att_id:
                                new_cache_entries[att_id] = {"type": "video", "name": name, "text": desc}
                        except Exception as e:
                            logging.error("No se pudo analizar video %s: %s", name, e, exc_info=True)
                            magna_warn(console, f"No se pudo analizar {name}: {e}")

        if ticket_id and new_cache_entries:
            save_processed_attachments(ticket_id, new_cache_entries)

        non_other = [
            a for a in attachments
            if not a.get("mimeType", "").startswith("image/")
            and a.get("mimeType", "") not in _EXCEL_MIME
            and a.get("mimeType", "") not in _VIDEO_MIME
        ]
        if non_other:
            magna_info(console, f"{len(non_other)} adjunto(s) de otro tipo incluido(s) como metadata")

    evidence_parts: list[str] = []
    if image_description:
        evidence_parts.append(f"Imagen de referencia: {image_description}")
    for name, desc in jira_images:
        evidence_parts.append(f"Imagen de Jira ({name}): {desc}")
    for name, desc in jira_excel:
        evidence_parts.append(f"Excel de Jira ({name}): {desc[:500]}")
    for name, desc in jira_videos:
        evidence_parts.append(f"Video de QA ({name}): {desc}")
    evidence_summary = "\n\n".join(evidence_parts) if evidence_parts else None

    with magna_status(console, "Generando plan de implementación..."):
        brief = _generate_task_brief(task_desc, relevant, file, evidence_summary)

    magna_task_plan(console, relevant, brief)

    from aicli.services.qa_protocol import is_bug_task
    es_bug = is_bug_task(task_desc, jira_data)

    context, ctx_warnings = build_context(relevant, project_path=path, es_bug=es_bug)
    for w in ctx_warnings:
        magna_warn(console, w)

    # Context receipt — detecta módulos que cambiaron desde la última sesión
    receipt_path = Path.home() / ".mycontext" / f"receipt_{project.id}.json"
    current_sig = {m.file_path: m.last_updated_at for m in relevant}
    if receipt_path.exists():
        try:
            prev_sig = json.loads(receipt_path.read_text(encoding="utf-8"))
            changed = [fp for fp, ts in current_sig.items() if fp not in prev_sig or prev_sig[fp] != ts]
            if changed:
                magna_warn(console, f"Contexto cambió desde la última sesión: {', '.join(changed)}")
        except Exception:
            pass
    receipt_path.write_text(json.dumps(current_sig, ensure_ascii=False), encoding="utf-8")

    if suspend_fn:
        suspend_fn(lambda: launch_claude(
            context, task_desc, brief, file, image_description,
            ticket_history, ticket_id, jira_data, jira_images, jira_excel, jira_videos,
        ))
    else:
        launch_claude(
            context, task_desc, brief, file, image_description,
            ticket_history, ticket_id, jira_data, jira_images, jira_excel, jira_videos,
        )


@app.callback(invoke_without_command=True)
def task(
    task_text: str = typer.Argument(..., help="Descripción de la tarea a realizar"),
    archivo: Annotated[Optional[str], typer.Option("--archivo", "-f", help="Ruta del archivo donde ocurre el problema")] = None,
    image: Annotated[Optional[str], typer.Option("--imagen", "-i", help="Ruta de imagen de referencia (screenshot, mockup)")] = None,
):
    """Detecta módulos relevantes para la tarea y lanza Claude con contexto y plan."""
    _execute_task(task_text, archivo, image)
