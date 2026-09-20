import typer
import json
import logging
import os
from typing import Annotated, Optional
from rich.console import Console
from pathlib import Path
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project, Module
from aicli.services.builder import build_context
from aicli.services.caller import launch_claude
from aicli.services.indexer import describe_image
from aicli.services.task_graph import run_task_graph
from aicli.tui.theme import magna_status, magna_ok, magna_warn, magna_error, magna_info, magna_panel, magna_task_plan, ACCENT, SECTION

app = typer.Typer()
console = Console()


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
        modules = list(session.exec(select(Module).where(Module.project_id == project.id).order_by(Module.id)).all())

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
    jira_docs:   list[tuple[str, str]] = []
    if jira_data and jira_data.get("attachments"):
        from aicli.services.jira import (
            download_image_attachments, download_excel_attachments,
            download_video_attachments, download_doc_attachments,
            excel_to_text, _EXCEL_MIME, _VIDEO_MIME, _DOC_MIME,
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
            elif cached_type == "doc":
                jira_docs.append(entry)

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
            doc_paths = download_doc_attachments(pending)

        if local_paths:
            magna_ok(console, f"{len(local_paths)} imagen(es) descargada(s) de Jira — Claude Code las leerá directamente")
        for img_path in local_paths:
            name = Path(img_path).name
            jira_images.append((name, img_path))
            att_id = id_by_filename.get(name)
            if att_id:
                new_cache_entries[att_id] = {"type": "image", "name": name, "text": img_path}

        if doc_paths:
            magna_ok(console, f"{len(doc_paths)} documento(s) descargado(s) de Jira — Claude Code los leerá directamente")
        for doc_path in doc_paths:
            name = Path(doc_path).name
            jira_docs.append((name, doc_path))
            att_id = id_by_filename.get(name)
            if att_id:
                new_cache_entries[att_id] = {"type": "doc", "name": name, "text": doc_path}

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
            and a.get("mimeType", "") not in _DOC_MIME
        ]
        if non_other:
            magna_info(console, f"{len(non_other)} adjunto(s) de otro tipo incluido(s) como metadata")

    evidence_parts: list[str] = []
    if image_description:
        evidence_parts.append(f"Imagen de referencia: {image_description}")
    for name, path in jira_images:
        evidence_parts.append(f"Imagen de Jira adjunta ({name}), sin analizar — ruta local: {path}")
    for name, desc in jira_excel:
        evidence_parts.append(f"Excel de Jira ({name}): {desc[:500]}")
    for name, desc in jira_videos:
        evidence_parts.append(f"Video de QA ({name}): {desc}")
    for name, path in jira_docs:
        evidence_parts.append(f"Documento de Jira adjunto ({name}), sin analizar — ruta local: {path}")
    evidence_summary = "\n\n".join(evidence_parts) if evidence_parts else None

    with magna_status(console, "Analizando tarea (detective · historiador · vigía)..."):
        relevant, brief = run_task_graph(task_desc, modules, file, project_context, evidence_summary)

    if not relevant:
        relevant = modules
    if file:                                   # guarantee union — se queda FUERA del grafo
        file_module = next((m for m in modules if m.file_path == file), None)
        if file_module and file_module not in relevant:
            relevant = [file_module] + relevant

    magna_task_plan(console, relevant, brief)

    context, ctx_warnings = build_context(relevant, project_path=path)
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
            ticket_history, ticket_id, jira_data, jira_images, jira_excel, jira_videos, jira_docs,
        ))
    else:
        launch_claude(
            context, task_desc, brief, file, image_description,
            ticket_history, ticket_id, jira_data, jira_images, jira_excel, jira_videos, jira_docs,
        )


@app.callback(invoke_without_command=True)
def task(
    task_text: str = typer.Argument(..., help="Descripción de la tarea a realizar"),
    archivo: Annotated[Optional[str], typer.Option("--archivo", "-f", help="Ruta del archivo donde ocurre el problema")] = None,
    image: Annotated[Optional[str], typer.Option("--imagen", "-i", help="Ruta de imagen de referencia (screenshot, mockup)")] = None,
):
    """Detecta módulos relevantes para la tarea y lanza Claude con contexto y plan."""
    _execute_task(task_text, archivo, image)
