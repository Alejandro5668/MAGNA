from pathlib import Path
from aicli.db.models import Module


def build_context(modules: list[Module]) -> str:
    fragments = []

    rol_path = Path.home() / ".mycontext" / "rol.md"
    if rol_path.exists():
        fragments.append(rol_path.read_text(encoding="utf-8"))

    # PROYECTO.md en ~/.mycontext/projects/<id>/ — fuera del repo, dentro del knowledge store
    if modules:
        project_id = modules[0].project_id
        proyecto_md = Path.home() / ".mycontext" / "projects" / str(project_id) / "PROYECTO.md"
        if proyecto_md.exists():
            content = proyecto_md.read_text(encoding="utf-8")
            fragments.append(f"# Conocimiento del proyecto\n\n{content}")

    for module in modules:
        path = Path(module.content_path)
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        fragments.append(
            f"## Módulo: {module.name}\n"
            f"**Archivo:** `{module.file_path}`\n\n"
            f"{content}"
        )
    return "\n\n---\n\n".join(fragments)