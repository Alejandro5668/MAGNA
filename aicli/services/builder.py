import os
import time
from pathlib import Path
from sqlmodel import Session, select
from aicli.db.models import Module, ModuleLesson
from aicli.db import engine


def build_context(modules: list[Module], project_path: Path | None = None) -> tuple[str, list[str]]:
    """
    Ensambla session_context.md a partir de módulos relevantes.
    Retorna (context_str, warnings) — warnings lista problemas de frescura detectados.
    """
    warnings: list[str] = []
    fragments: list[str] = []

    rol_path = Path.home() / ".mycontext" / "rol.md"
    if rol_path.exists():
        fragments.append(rol_path.read_text(encoding="utf-8"))

    if modules:
        project_id = modules[0].project_id
        proyecto_md = Path.home() / ".mycontext" / "projects" / str(project_id) / "PROYECTO.md"
        if proyecto_md.exists():
            age_days = (time.time() - proyecto_md.stat().st_mtime) / 86400
            if age_days > 30:
                warnings.append(f"PROYECTO.md tiene {int(age_days)} días — ejecutá ctx proyecto para actualizar")
            content = proyecto_md.read_text(encoding="utf-8")
            fragments.append(f"# Conocimiento del proyecto\n\n{content}")

        # Pre-cargar lecciones de todos los módulos en una sola query
        file_paths = [m.file_path for m in modules]
        with Session(engine) as session:
            all_lessons = list(session.exec(
                select(ModuleLesson)
                .where(ModuleLesson.project_id == project_id)
            ).all())
        lessons_by_path: dict[str, list[ModuleLesson]] = {}
        for lesson in sorted(all_lessons, key=lambda l: l.date, reverse=True):
            bucket = lessons_by_path.setdefault(lesson.file_path, [])
            if len(bucket) < 3:
                bucket.append(lesson)

    stale: list[str] = []
    for module in modules:
        # Freshness check — el archivo fuente cambió después de la última documentación
        if project_path and module.file_path and module.last_updated_at:
            source = project_path / module.file_path
            if source.exists() and os.path.getmtime(source) > module.last_updated_at:
                stale.append(module.file_path)

        md_path = Path(module.content_path)
        if not md_path.exists():
            continue
        content = md_path.read_text(encoding="utf-8", errors="replace")

        lesson_text = ""
        module_lessons = lessons_by_path.get(module.file_path, [])
        if module_lessons:
            lines = [f"- [{l.date}] {l.lesson}" for l in module_lessons]
            lesson_text = "\n\n**Lecciones aprendidas:**\n" + "\n".join(lines)

        fragments.append(
            f"## Módulo: {module.name}\n"
            f"**Archivo:** `{module.file_path}`\n\n"
            f"{content}"
            f"{lesson_text}"
        )

    if stale:
        warnings.append(f"Documentación desactualizada en: {', '.join(stale)} — ejecutá ctx sync")

    return "\n\n---\n\n".join(fragments), warnings
