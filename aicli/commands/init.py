import typer
import time
from typing import Annotated, Optional
from rich.console import Console, Group
from rich.panel import Panel
from pathlib import Path
from datetime import datetime
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project, Module
from aicli.services.indexer import (
    indexar_proyecto,
    indexar_arbol,
    obtener_arbol,
    obtener_arbol_zona,
    obtener_archivos_recientes,
    documentar_arquitectura,
    generar_contenido_modulo,
    modulo_necesita_actualizacion,
    EXTENSIONES_NO_CODIGO,
    UMBRAL_MODO_ARQUITECTURA,
)

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


def _progreso_print(msg: str) -> None:
    console.print(f"  [bold green]✔[/bold green] [dim]{msg}[/dim]")


def _ruta_md(proyecto_id: int, file_path: str) -> Path:
    """Espeja la estructura del proyecto: pagos/X.php → ~/.mycontext/projects/42/pagos/X.md"""
    base = Path.home() / ".mycontext" / "projects" / str(proyecto_id)
    return base / Path(file_path).with_suffix(".md")


def _guardar_modulos(modulos: list[dict], proyecto: Project) -> None:
    with Session(engine) as session:
        for m in modulos:
            archivo_md = _ruta_md(proyecto.id, m["file_path"])
            archivo_md.parent.mkdir(parents=True, exist_ok=True)
            archivo_md.write_text(m["content_md"], encoding="utf-8")
            modulo = Module(
                project_id=proyecto.id,
                name=m["name"],
                description=m["description"],
                file_path=m["file_path"],
                content_path=str(archivo_md),
                created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                last_updated_at=m.get("last_updated_at"),
                category=m.get("category"),
                domain=m.get("domain"),
            )
            session.add(modulo)
            session.commit()


def _mostrar_guia_proyecto_grande(name: str, n_codigo: int) -> None:
    console.print(Panel(
        Group(
            f"[bold]{name}[/bold] tiene [bold cyan]{n_codigo:,}[/bold cyan] archivos de código.",
            "[dim]Documentar todo el proyecto no es viable. Elegí un modo:[/dim]",
            "",
            "  [bold cyan]ctx init --zona <carpeta>[/bold cyan]",
            "  [dim]Documenta solo esa área.  Ej: ctx init --zona controllers/pagos[/dim]",
            "",
            "  [bold cyan]ctx init --reciente 90[/bold cyan]",
            "  [dim]Solo archivos modificados en los últimos 90 días (requiere git)[/dim]",
            "",
            "  [bold cyan]ctx init --arquitectura[/bold cyan]",
            "  [dim]Lee código real de cada módulo y genera un mapa del sistema completo[/dim]",
        ),
        title="Proyecto grande detectado",
        border_style="yellow"
    ))


@app.callback(invoke_without_command=True)
def init(
    zona: Annotated[Optional[str], typer.Option("--zona", "-z", help="Documentar solo esta carpeta o área")] = None,
    reciente: Annotated[Optional[int], typer.Option("--reciente", "-r", help="Archivos modificados en los últimos N días")] = None,
    arquitectura: Annotated[bool, typer.Option("--arquitectura", "-a", help="Mapa estructural del sistema")] = False,
):
    """Registra el proyecto activo y documenta sus módulos con IA."""
    path = Path.cwd()
    name = path.name
    stack = detectar_stack(path)

    arbol = obtener_arbol(path)
    n_codigo = len([f for f in arbol if Path(f).suffix not in EXTENSIONES_NO_CODIGO])
    modo_especifico = zona or (reciente is not None) or arquitectura

    # Proyecto grande sin modo explícito → mostrar guía y preguntar
    if n_codigo > UMBRAL_MODO_ARQUITECTURA and not modo_especifico:
        _mostrar_guia_proyecto_grande(name, n_codigo)

        import questionary
        from questionary import Style as QStyle

        _estilo = QStyle([
            ("qmark",       "fg:cyan bold"),
            ("question",    "fg:white bold"),
            ("pointer",     "fg:cyan bold"),
            ("highlighted", "fg:cyan bold"),
            ("selected",    "fg:cyan"),
            ("answer",      "fg:cyan bold"),
        ])

        eleccion = questionary.select(
            "¿Qué modo querés usar?",
            choices=[
                questionary.Choice("  --zona          → Documentar una carpeta específica", value="zona"),
                questionary.Choice("  --reciente      → Archivos modificados en los últimos N días", value="reciente"),
                questionary.Choice("  --arquitectura  → Mapa estructural del sistema", value="arquitectura"),
                questionary.Choice("  Cancelar", value="cancelar"),
            ],
            style=_estilo,
        ).ask()

        if eleccion is None or eleccion == "cancelar":
            return

        if eleccion == "zona":
            zona = questionary.text(
                "  Ruta de la carpeta (ej: controllers/pagos)",
                style=_estilo
            ).ask()
            if not zona or not zona.strip():
                return
            zona = zona.strip()

        elif eleccion == "reciente":
            dias_str = questionary.text(
                "  ¿Cuántos días atrás?",
                default="90",
                style=_estilo
            ).ask()
            try:
                reciente = int(dias_str.strip())
            except (ValueError, AttributeError):
                reciente = 90

        elif eleccion == "arquitectura":
            arquitectura = True

        modo_especifico = True

    with Session(engine) as session:
        proyecto_existente = session.exec(select(Project).where(Project.path == str(path))).first()

    # Proyecto normal sin modo explícito → actualización incremental si ya existe
    if proyecto_existente and not modo_especifico:
        _actualizar_proyecto(proyecto_existente, path)
        return

    # Registrar proyecto si no existe aún
    if proyecto_existente:
        proyecto = proyecto_existente
    else:
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

    # ── Modo zona ──────────────────────────────────────────────────────────
    if zona:
        try:
            arbol_zona = obtener_arbol_zona(path, zona)
        except ValueError as e:
            console.print(f"[bold red]Error:[/bold red] {e}")
            raise typer.Exit(code=1)

        n_zona = len([f for f in arbol_zona if Path(f).suffix not in EXTENSIONES_NO_CODIGO])
        console.print(f"\n[bold cyan]Documentando zona '{zona}' en {name}...[/bold cyan]")
        console.print(f"  [dim]{n_zona:,} archivos de código en esta zona[/dim]")
        modulos = indexar_arbol(path, name, stack, arbol_zona, on_progreso=_progreso_print)
        modo_label = f"zona '{zona}'"

    # ── Modo reciente ───────────────────────────────────────────────────────
    elif reciente is not None:
        archivos = obtener_archivos_recientes(path, reciente)
        if not archivos:
            console.print(f"[bold yellow]Aviso:[/bold yellow] No se encontraron archivos modificados en los últimos {reciente} días.")
            console.print("  ¿Es este directorio un repositorio git con historial?")
            raise typer.Exit(code=1)
        console.print(f"\n[bold cyan]Documentando archivos recientes de {name}...[/bold cyan]")
        console.print(f"  [dim]{len(archivos):,} archivos modificados en los últimos {reciente} días[/dim]")
        modulos = indexar_arbol(path, name, stack, archivos, on_progreso=_progreso_print)
        modo_label = f"últimos {reciente} días"

    # ── Modo arquitectura ───────────────────────────────────────────────────
    elif arquitectura:
        console.print(f"\n[bold cyan]Mapeando arquitectura de {name}...[/bold cyan]")
        console.print(f"  [dim]{n_codigo:,} archivos de código · {len(arbol):,} archivos totales[/dim]")
        modulos_raw = documentar_arquitectura(path, name, stack, arbol, on_progreso=_progreso_print)
        modulos = []
        for m in modulos_raw:
            m["content_md"] = m.pop("documentation", "")
            m["last_updated_at"] = time.time()
            modulos.append(m)
        modo_label = "arquitectura"

    # ── Modo normal (primera vez, proyecto no grande) ───────────────────────
    else:
        console.print(f"\n[bold cyan]Analizando {name} ({stack})...[/bold cyan]")
        modulos = indexar_proyecto(path, name, stack, on_progreso=_progreso_print)
        modo_label = stack

    _guardar_modulos(modulos, proyecto)

    console.print(Panel(
        Group(
            f"[bold cyan]✔ {name} — {len(modulos)} módulos documentados[/bold cyan]",
            f"[bold dim]Modo: {modo_label}[/bold dim]",
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