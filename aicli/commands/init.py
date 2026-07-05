import typer
import time
from rich.console import Console, Group
from rich.panel import Panel
from pathlib import Path
from datetime import datetime
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project, Module
from aicli.services.indexer import (
    get_tree,
    document_architecture,
    generate_module_content,
    module_needs_update,
    NON_CODE_EXTENSIONS,
)
from aicli.tui.theme import magna_ok, magna_warn, magna_info, magna_status, ACCENT, SECTION

app = typer.Typer()
console = Console()

_ROL_DEFAULT = """# Instrucciones — Claude Code + AICLI

## Contexto de sesión
AICLI ha cargado documentación del proyecto en este archivo de contexto.
Si un módulo no aparece en el contexto, leé el archivo real antes de hacer suposiciones.

## Idioma
Respondé siempre en **español**. Código, variables y comentarios: en el idioma que ya usa el proyecto.

## Estilo de respuesta
- Una oración de qué vas a hacer antes del primer tool call.
- Actualizaciones breves cuando encuentres algo relevante o cambies de dirección.
- Al final: 1-2 oraciones — qué cambió y qué sigue.
- Referenciá código como `archivo.php:línea`.

## Rol técnico
Actuá como desarrollador senior con 10+ años en PHP, MySQL y JavaScript:
- Identificá el patrón del código antes de proponer cambios.
- Seguí el estilo existente del archivo — no introduzcas convenciones nuevas.
- Explicá la causa raíz antes de proponer el fix de un bug.
- No agregues features ni abstracciones más allá de lo pedido.
- Editá archivos existentes antes de crear nuevos.

## SQL — verificación obligatoria
**Nunca asumas nombres de tablas o campos.**
Antes de cualquier query:
1. Leé `*_querys.php` del módulo → tablas reales en los FROM/JOIN de `$querys[]`.
2. Usá los alias exactos del SELECT de ese archivo.
3. Considerá el impacto multi-tenant: todo filtro por empresa/sesión.
4. Incluí un SELECT de verificación antes de cualquier UPDATE/DELETE en producción.

## Confirmación obligatoria antes de:
- Queries UPDATE/DELETE/DROP sobre datos de producción.
- Borrar archivos, ramas o contenido irreversible.
- Push a repositorios remotos o acciones visibles para otros.
"""


def detect_stack(path: Path) -> str:
    if (path / "requirements.txt").exists() or (path / "pyproject.toml").exists():
        return "python"
    if (path / "composer.json").exists():
        return "laravel"
    if (path / "pom.xml").exists():
        return "java"
    if (path / "build.gradle").exists() or (path / "build.gradle.kts").exists():
        return "kotlin"
    if (path / "Cargo.toml").exists():
        return "rust"
    if (path / "go.mod").exists():
        return "go"
    if (path / "package.json").exists():
        pkg = path / "package.json"
        try:
            import json
            data = json.loads(pkg.read_text(encoding="utf-8"))
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            if "next" in deps:
                return "nextjs"
            if "nuxt" in deps:
                return "nuxt"
            if "react" in deps:
                return "react"
            if "vue" in deps:
                return "vue"
            if "@angular/core" in deps:
                return "angular"
            if "svelte" in deps:
                return "svelte"
            if "express" in deps or "fastify" in deps or "koa" in deps:
                return "nodejs"
            if "typescript" in deps or (path / "tsconfig.json").exists():
                return "typescript"
        except Exception:
            pass
        return "javascript"
    if (path / "Gemfile").exists():
        return "ruby"
    if (path / "pubspec.yaml").exists():
        return "flutter"
    if (path / "mix.exs").exists():
        return "elixir"
    # PHP puro sin composer.json — solo raíz para no escanear miles de archivos
    if any(path.glob("*.php")):
        return "php"
    return "desconocido"


def _progreso_print(msg: str) -> None:
    magna_ok(console, msg)


def _md_path(project_id: int, file_path: str) -> Path:
    base = Path.home() / ".mycontext" / "projects" / str(project_id)
    return base / Path(file_path).with_suffix(".md")


def _save_modules(modules: list[dict], project: Project) -> None:
    with Session(engine) as session:
        for m in modules:
            md_file = _md_path(project.id, m["file_path"])
            md_file.parent.mkdir(parents=True, exist_ok=True)
            md_file.write_text(m.get("content_md", m.get("documentation", "")), encoding="utf-8")

            existing = session.exec(
                select(Module).where(
                    Module.file_path == m["file_path"],
                    Module.project_id == project.id
                )
            ).first()

            if existing:
                existing.content_path = str(md_file)
                existing.last_updated_at = m.get("last_updated_at", time.time())
                existing.description = m.get("description", existing.description)
                session.add(existing)
            else:
                session.add(Module(
                    project_id=project.id,
                    name=m["name"],
                    description=m.get("description", ""),
                    file_path=m["file_path"],
                    content_path=str(md_file),
                    created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    last_updated_at=m.get("last_updated_at", time.time()),
                    category=m.get("category"),
                    domain=m.get("domain"),
                ))
        session.commit()


def _create_rol_if_missing() -> None:
    rol_path = Path.home() / ".mycontext" / "rol.md"
    if not rol_path.exists():
        rol_path.write_text(_ROL_DEFAULT, encoding="utf-8")


@app.callback(invoke_without_command=True)
def init():
    """Registra el proyecto activo y genera su mapa arquitectural con IA."""
    from aicli.services.activity import log_activity
    log_activity("init")
    path = Path.cwd()
    name = path.name
    stack = detect_stack(path)

    _create_rol_if_missing()

    with Session(engine) as session:
        existing_project = session.exec(select(Project).where(Project.path == str(path))).first()

    if existing_project:
        _update_project(existing_project, path)
        return

    project = Project(
        name=name,
        path=str(path),
        stack=stack,
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    with Session(engine) as session:
        session.add(project)
        session.commit()
        session.refresh(project)

    tree = get_tree(path)
    n_code = len([f for f in tree if Path(f).suffix not in NON_CODE_EXTENSIONS])

    console.print(f"\n[bold {ACCENT}]Mapeando arquitectura de {name}...[/bold {ACCENT}]")
    magna_info(console, f"{n_code:,} archivos de código · {stack}")

    raw_modules = document_architecture(path, name, stack, tree, on_progreso=_progreso_print)
    modules = [
        {**m, "content_md": m.pop("documentation", ""), "last_updated_at": time.time()}
        for m in raw_modules
    ]

    _save_modules(modules, project)

    console.print(Panel(
        Group(
            f"[bold #4ADE80]✔ {name} — {len(modules)} módulos documentados[/bold #4ADE80]",
            f"[{SECTION}]Stack: {stack}[/{SECTION}]",
            f"[{SECTION}]Ruta: {path}[/{SECTION}]",
        ),
        title="ctx init",
        border_style="#4ADE80",
    ))

    console.print(Panel(
        Group(
            f"[bold #F1F3F9]Ponytail[/bold #F1F3F9] reduce el código que genera Claude entre 80–94%.",
            f"[{SECTION}]Ejecutá estos comandos en cualquier sesión de Claude Code:[/{SECTION}]",
            "",
            f"  [bold {ACCENT}]/plugin marketplace add DietrichGebert/ponytail[/bold {ACCENT}]",
            f"  [bold {ACCENT}]/plugin install ponytail@ponytail[/bold {ACCENT}]",
        ),
        title=f"[{SECTION}]Plus recomendado[/{SECTION}]",
        border_style=SECTION,
    ))


def _update_project(project: Project, path: Path) -> None:
    with Session(engine) as session:
        modules_db = list(session.exec(select(Module).where(Module.project_id == project.id)).all())

    updated = 0
    unchanged = 0

    console.print(f"\n[bold {ACCENT}]Verificando módulos de {project.name}...[/bold {ACCENT}]")
    for module in modules_db:
        if module_needs_update(module.file_path, path, module):
            source_file = path / module.file_path
            try:
                source = source_file.read_text(encoding="latin-1")
            except FileNotFoundError:
                magna_warn(console, f"{module.file_path} — no encontrado, se omite")
                continue

            content_md, tokens = generate_module_content(module.name, module.file_path, source)
            md_file = _md_path(project.id, module.file_path)
            md_file.parent.mkdir(parents=True, exist_ok=True)
            md_file.write_text(content_md, encoding="utf-8")

            with Session(engine) as session:
                m = session.get(Module, module.id)
                m.content_path = str(md_file)
                m.last_updated_at = time.time()
                session.add(m)
                session.commit()

            magna_ok(console, f"{module.file_path} — actualizado · {tokens:,} tokens")
            updated += 1
        else:
            magna_info(console, f"✔ {module.file_path} — sin cambios")
            unchanged += 1

    console.print(Panel(
        Group(
            f"[bold {ACCENT}]{project.name} — contexto al día[/bold {ACCENT}]",
            f"[{SECTION}]Actualizados: {updated}  |  Sin cambios: {unchanged}[/{SECTION}]",
        ),
        title="ctx init",
        border_style=ACCENT,
    ))