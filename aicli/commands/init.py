import typer
import time
from rich.console import Console, Group
from rich.panel import Panel
from pathlib import Path
from datetime import datetime
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project, Module
from aicli.services.indexer import indexar_proyecto, generar_contenido_modulo, modulo_necesita_actualizacion

app = typer.Typer()
console = Console()


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
    if (path / "*.csproj").exists() or (path / "*.sln").exists():
        return "dotnet"
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
    return "desconocido"


@app.callback(invoke_without_command=True)
def init():
    """Registra el proyecto activo y documenta sus módulos con IA."""
    path = Path.cwd()
    name = path.name
    stack = detectar_stack(path)

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

    with console.status("Analizando proyecto con IA...", spinner="dots3", spinner_style="cyan"):
        modulos = indexar_proyecto(path, name, stack)
        directorio = Path.home() / ".mycontext" / "projects" / str(proyecto.id)
        directorio.mkdir(parents=True, exist_ok=True)

        for m in modulos:
            archivo_md = directorio / f"{m['name']}.md"
            archivo_md.write_text(m["content_md"], encoding="utf-8")
            m["content_path"] = str(archivo_md)

    with Session(engine) as session:
        for m in modulos:
            modulo = Module(
                project_id=proyecto.id,
                name=m["name"],
                description=m["description"],
                file_path=m["file_path"],
                content_path=m["content_path"],
                created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                last_updated_at=m.get("last_updated_at"),
                category=m.get("category"),
                domain=m.get("domain"),
            )
            session.add(modulo)
            session.commit()

    contenido_panel = Group(
        f"[bold cyan]✔ Proyecto [bold]{name}[/bold] registrado[/bold cyan]",
        f"[bold dim]Stack: {stack}[/bold dim]",
        f"[bold dim]Ruta: {path}[/bold dim]",
        f"[bold dim]Módulos documentados: {len(modulos)}[/bold dim]",
    )
    console.print(Panel(contenido_panel, title="Registro Exitoso", border_style="green"))


def _actualizar_proyecto(proyecto: Project, path: Path) -> None:
    with Session(engine) as session:
        modulos_db = list(session.exec(select(Module).where(Module.project_id == proyecto.id)).all())

    actualizados = 0
    sin_cambios = 0
    directorio = Path.home() / ".mycontext" / "projects" / str(proyecto.id)
    directorio.mkdir(parents=True, exist_ok=True)

    with console.status("Verificando módulos...", spinner="dots3", spinner_style="cyan"):
        for modulo in modulos_db:
            if modulo_necesita_actualizacion(modulo.file_path, path, modulo):
                ruta_fuente = path / modulo.file_path
                try:
                    fuente = ruta_fuente.read_text(encoding="utf-8")
                except FileNotFoundError:
                    console.print(f"[bold yellow]⚠[/bold yellow] {modulo.file_path} — archivo no encontrado, se omite")
                    continue

                contenido_md = generar_contenido_modulo(modulo.name, modulo.file_path, fuente)
                archivo_md = directorio / f"{modulo.name}.md"
                archivo_md.write_text(contenido_md, encoding="utf-8")

                with Session(engine) as session:
                    m = session.get(Module, modulo.id)
                    m.content_path = str(archivo_md)
                    m.last_updated_at = time.time()
                    session.add(m)
                    session.commit()

                console.print(f"[bold green]✔[/bold green] {modulo.file_path} — actualizado")
                actualizados += 1
            else:
                console.print(f"[dim]✔ {modulo.file_path} — sin cambios[/dim]")
                sin_cambios += 1

    contenido_panel = Group(
        f"[bold cyan]Proyecto [bold]{proyecto.name}[/bold] — contexto al día[/bold cyan]",
        f"[bold dim]Actualizados: {actualizados}  |  Sin cambios: {sin_cambios}[/bold dim]",
    )
    console.print(Panel(contenido_panel, title="ctx init", border_style="cyan"))