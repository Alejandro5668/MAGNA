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
    generate_role_md,
    module_needs_update,
    NON_CODE_EXTENSIONS,
    _write_md_atomic,
)
from aicli.services.stack_profile import get_adapter
from aicli.tui.theme import magna_ok, magna_warn, magna_info, ACCENT, SECTION

app = typer.Typer()
console = Console()


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
            _write_md_atomic(md_file, m.get("content_md", m.get("documentation", "")))

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


def _create_rol_if_missing(
    role_template: str, path: Path, name: str, stack: str,
    tree: list[str], encoding: str,
) -> None:
    rol_path = Path.home() / ".mycontext" / "rol.md"
    if not rol_path.exists():
        content = generate_role_md(path, name, stack, tree, fallback=role_template, encoding=encoding)
        _write_md_atomic(rol_path, content)


@app.callback(invoke_without_command=True)
def init():
    """Registra el proyecto activo y genera su mapa arquitectural con IA."""
    from aicli.services.activity import log_activity
    log_activity("init")
    path = Path.cwd()
    name = path.name
    stack = detect_stack(path)
    adapter = get_adapter(stack)

    with Session(engine) as session:
        existing_project = session.exec(select(Project).where(Project.path == str(path))).first()

    if existing_project:
        _update_project(existing_project, path, adapter.encoding)
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
    tree = adapter.filter_files(tree)
    domains = adapter.suggest_domains(tree)
    arch_hint = adapter.build_architecture_hint()
    if domains:
        arch_hint += f"\n\nDominios principales detectados: {', '.join(domains)}."

    _create_rol_if_missing(adapter.role_template, path, name, stack, tree, adapter.encoding)
    n_code = len([f for f in tree if Path(f).suffix not in NON_CODE_EXTENSIONS])

    console.print(f"\n[bold {ACCENT}]Mapeando arquitectura de {name}...[/bold {ACCENT}]")
    magna_info(console, f"{n_code:,} archivos de código · {stack}")

    raw_modules = document_architecture(
        path, name, stack, tree,
        on_progreso=_progreso_print,
        encoding=adapter.encoding,
        hints=arch_hint,
    )
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


def _update_project(project: Project, path: Path, encoding: str = "utf-8") -> None:
    with Session(engine) as session:
        modules_db = list(session.exec(select(Module).where(Module.project_id == project.id)).all())

    updated = 0
    unchanged = 0

    console.print(f"\n[bold {ACCENT}]Verificando módulos de {project.name}...[/bold {ACCENT}]")
    for module in modules_db:
        if module_needs_update(module.file_path, path, module):
            source_file = path / module.file_path
            try:
                source = source_file.read_text(encoding=encoding)
            except FileNotFoundError:
                magna_warn(console, f"{module.file_path} — no encontrado, se omite")
                continue

            content_md, tokens = generate_module_content(module.name, module.file_path, source)
            md_file = _md_path(project.id, module.file_path)
            md_file.parent.mkdir(parents=True, exist_ok=True)
            _write_md_atomic(md_file, content_md)

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