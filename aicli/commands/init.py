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
    obtener_arbol,
    documentar_arquitectura,
    generar_contenido_modulo,
    modulo_necesita_actualizacion,
    EXTENSIONES_NO_CODIGO,
)

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


def detectar_stack(path: Path) -> str:
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
    # PHP puro sin composer.json
    php_files = list(path.rglob("*.php"))
    if len(php_files) > 10:
        return "php"
    return "desconocido"


def _progreso_print(msg: str) -> None:
    console.print(f"  [bold green]✔[/bold green] [dim]{msg}[/dim]")


def _ruta_md(proyecto_id: int, file_path: str) -> Path:
    base = Path.home() / ".mycontext" / "projects" / str(proyecto_id)
    return base / Path(file_path).with_suffix(".md")


def _guardar_modulos(modulos: list[dict], proyecto: Project) -> None:
    with Session(engine) as session:
        for m in modulos:
            archivo_md = _ruta_md(proyecto.id, m["file_path"])
            archivo_md.parent.mkdir(parents=True, exist_ok=True)
            archivo_md.write_text(m.get("content_md", m.get("documentation", "")), encoding="utf-8")

            existente = session.exec(
                select(Module).where(
                    Module.file_path == m["file_path"],
                    Module.project_id == proyecto.id
                )
            ).first()

            if existente:
                existente.content_path = str(archivo_md)
                existente.last_updated_at = m.get("last_updated_at", time.time())
                existente.description = m.get("description", existente.description)
                session.add(existente)
            else:
                session.add(Module(
                    project_id=proyecto.id,
                    name=m["name"],
                    description=m.get("description", ""),
                    file_path=m["file_path"],
                    content_path=str(archivo_md),
                    created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    last_updated_at=m.get("last_updated_at", time.time()),
                    category=m.get("category"),
                    domain=m.get("domain"),
                ))
        session.commit()


def _crear_rol_si_no_existe() -> None:
    rol_path = Path.home() / ".mycontext" / "rol.md"
    if not rol_path.exists():
        rol_path.write_text(_ROL_DEFAULT, encoding="utf-8")


@app.callback(invoke_without_command=True)
def init():
    """Registra el proyecto activo y genera su mapa arquitectural con IA."""
    path = Path.cwd()
    name = path.name
    stack = detectar_stack(path)

    _crear_rol_si_no_existe()

    with Session(engine) as session:
        proyecto_existente = session.exec(select(Project).where(Project.path == str(path))).first()

    if proyecto_existente:
        _actualizar_proyecto(proyecto_existente, path)
        return

    proyecto = Project(
        name=name,
        path=str(path),
        stack=stack,
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    with Session(engine) as session:
        session.add(proyecto)
        session.commit()
        session.refresh(proyecto)

    arbol = obtener_arbol(path)
    n_codigo = len([f for f in arbol if Path(f).suffix not in EXTENSIONES_NO_CODIGO])

    console.print(f"\n[bold cyan]Mapeando arquitectura de {name}...[/bold cyan]")
    console.print(f"  [dim]{n_codigo:,} archivos de código · {stack}[/dim]")

    modulos_raw = documentar_arquitectura(path, name, stack, arbol, on_progreso=_progreso_print)
    modulos = [
        {**m, "content_md": m.pop("documentation", ""), "last_updated_at": time.time()}
        for m in modulos_raw
    ]

    _guardar_modulos(modulos, proyecto)

    console.print(Panel(
        Group(
            f"[bold cyan]✔ {name} — {len(modulos)} módulos documentados[/bold cyan]",
            f"[bold dim]Stack: {stack}[/bold dim]",
            f"[bold dim]Ruta: {path}[/bold dim]",
        ),
        title="ctx init",
        border_style="green"
    ))


def _actualizar_proyecto(proyecto: Project, path: Path) -> None:
    with Session(engine) as session:
        modulos_db = list(session.exec(select(Module).where(Module.project_id == proyecto.id)).all())

    actualizados = 0
    sin_cambios = 0

    console.print(f"\n[bold cyan]Verificando módulos de {proyecto.name}...[/bold cyan]")
    for modulo in modulos_db:
        if modulo_necesita_actualizacion(modulo.file_path, path, modulo):
            ruta_fuente = path / modulo.file_path
            try:
                fuente = ruta_fuente.read_text(encoding="utf-8")
            except FileNotFoundError:
                console.print(f"  [bold yellow]⚠[/bold yellow] [dim]{modulo.file_path} — no encontrado, se omite[/dim]")
                continue

            contenido_md, tokens = generar_contenido_modulo(modulo.name, modulo.file_path, fuente)
            archivo_md = _ruta_md(proyecto.id, modulo.file_path)
            archivo_md.parent.mkdir(parents=True, exist_ok=True)
            archivo_md.write_text(contenido_md, encoding="utf-8")

            with Session(engine) as session:
                m = session.get(Module, modulo.id)
                m.content_path = str(archivo_md)
                m.last_updated_at = time.time()
                session.add(m)
                session.commit()

            console.print(f"  [bold green]✔[/bold green] [dim]{modulo.file_path} — actualizado · {tokens:,} tokens[/dim]")
            actualizados += 1
        else:
            console.print(f"  [dim]✔ {modulo.file_path} — sin cambios[/dim]")
            sin_cambios += 1

    console.print(Panel(
        Group(
            f"[bold cyan]{proyecto.name} — contexto al día[/bold cyan]",
            f"[bold dim]Actualizados: {actualizados}  |  Sin cambios: {sin_cambios}[/bold dim]",
        ),
        title="ctx init",
        border_style="cyan"
    ))