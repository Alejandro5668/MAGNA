import subprocess
import logging
import platform
import os
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.console import Group

console = Console()

# Rutas conocidas donde Claude Code suele instalarse en Windows
_CLAUDE_WINDOWS_PATHS = [
    Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd",
    Path(os.environ.get("APPDATA", "")) / "npm" / "claude",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Claude" / "claude.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "npm" / "claude.cmd",
    Path.home() / "AppData" / "Roaming" / "npm" / "claude.cmd",
]


def _find_claude_windows() -> Path | None:
    """Busca claude.cmd en rutas conocidas de Windows."""
    for path in _CLAUDE_WINDOWS_PATHS:
        if path.exists():
            return path

    # Intentar con where.exe como segunda opción
    try:
        result = subprocess.run(
            ["where", "claude"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            first = result.stdout.strip().splitlines()[0].strip()
            if first:
                return Path(first)
    except Exception:
        pass

    return None


def _diagnose_and_retry(message: str) -> bool:
    """
    Muestra diagnóstico específico cuando claude no se encuentra.
    Retorna True si el usuario quiere reintentar.
    """
    is_windows = platform.system() == "Windows"
    found_path = _find_claude_windows() if is_windows else None

    if found_path:
        # Instalado pero no en el PATH del proceso actual
        folder = str(found_path.parent)
        lines = [
            f"[bold green]✔[/bold green] Claude Code encontrado en:",
            f"  [dim]{found_path}[/dim]",
            "",
            "[bold red]✘[/bold red] Problema: no está en el PATH del proceso actual.",
            "  (Común cuando AICLI corre como .exe — el entorno es diferente al de tu terminal)",
            "",
            "[bold cyan]Solución A — temporal (solo esta sesión):[/bold cyan]",
            f"  Abrí PowerShell y ejecutá:",
            f"  [bold]$env:PATH += \";{folder}\"[/bold]",
            "  Luego reiniciá AICLI.",
            "",
            "[bold cyan]Solución B — permanente:[/bold cyan]",
            "  Inicio → Buscar 'Variables de entorno' → PATH → Nueva →",
            f"  Agregar: [bold]{folder}[/bold]",
            "  Cerrar y reabrir AICLI.",
        ]
    else:
        # No encontrado en ningún lado
        lines = [
            "[bold red]✘[/bold red] Claude Code no está instalado o no se encontró.",
            "",
            "[bold cyan]Instalación — ejecutá en PowerShell:[/bold cyan]",
            "  [bold]npm install -g @anthropic-ai/claude-code[/bold]",
            "",
            "  (Necesitás Node.js instalado. Verificá con: [bold]node --version[/bold])",
            "",
            "[bold cyan]Verificación — después de instalar:[/bold cyan]",
            "  [bold]claude --version[/bold]",
            "",
            "[bold cyan]Documentación oficial:[/bold cyan]",
            "  claude.ai/code",
        ]

    lines += [
        "",
        "[dim]El contexto de la tarea ya está guardado en session_context.md[/dim]",
        "[dim]Podés lanzar claude manualmente con el archivo de contexto si preferís.[/dim]",
    ]

    console.print(Panel(
        Group(*lines),
        title="[bold yellow]Claude Code no encontrado[/bold yellow]",
        border_style="yellow"
    ))

    try:
        import questionary
        from questionary import Style as QStyle
        response = questionary.confirm(
            "¿Reintentar ahora?",
            default=False,
            style=QStyle([("question", "fg:white bold"), ("answer", "fg:cyan bold")])
        ).ask()
        return bool(response)
    except Exception:
        return False


def launch_claude(
    context: str,
    task: str | None = None,
    brief: str | None = None,
    file: str | None = None,
    image_description: str | None = None,
    ticket_history: str | None = None,
) -> None:
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ctx_path = Path.home() / ".mycontext" / f"session_context_{ts}.md"
    content = f"# Contexto del proyecto cargado por AICLI\n\n{context}"
    if ticket_history:
        content += f"\n\n---\n\n# Historial del ticket\n\n{ticket_history}"
    if brief:
        content += f"\n\n---\n\n# Plan de implementación\n\n{brief}"
    if image_description:
        content += f"\n\n---\n\n# Imagen de referencia\n\n{image_description}"
    if file:
        content += f"\n\n---\n\n# Archivo de entrada\n`{file}`"
    if task:
        content += f"\n\n---\n\n# Tarea\n{task}"
    ctx_path.write_text(content, encoding="utf-8")

    message = f"Read {ctx_path} to get the project context and task, then start working."

    is_windows = platform.system() == "Windows"
    claude_path = _find_claude_windows() if is_windows else None

    for attempt in range(2):
        try:
            if claude_path and is_windows:
                subprocess.run([str(claude_path), message], check=False, shell=False)
            else:
                subprocess.run(["claude", message], check=False, shell=is_windows)
            return
        except FileNotFoundError:
            logging.error("launch_claude — 'claude' no encontrado en intento %d", attempt + 1)
            retry = _diagnose_and_retry(message)
            if not retry or attempt == 1:
                return
            claude_path = _find_claude_windows() if is_windows else None
        except Exception as e:
            logging.error("launch_claude — error al lanzar Claude: %s", e, exc_info=True)
            console.print(f"[bold red]Error inesperado al lanzar Claude:[/bold red] {e}")
            return