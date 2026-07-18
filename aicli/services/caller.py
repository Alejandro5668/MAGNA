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


def _set_terminal_title(title: str) -> None:
    print(f"\033]0;{title}\007", end="", flush=True)
    if platform.system() == "Windows":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(title)
        except Exception:
            pass


def launch_claude(
    context: str,
    task: str | None = None,
    brief: str | None = None,
    file: str | None = None,
    image_description: str | None = None,
    ticket_history: str | None = None,
    ticket_id: str | None = None,
    jira_data: dict | None = None,
    jira_images: list | None = None,
    jira_excel: list | None = None,
    question_mode: bool = False,
) -> None:
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ctx_path = Path.home() / ".mycontext" / f"session_context_{ts}.md"
    content = f"# Contexto del proyecto cargado por AICLI\n\n{context}"
    if ticket_history:
        content += f"\n\n---\n\n# Historial del ticket\n\n{ticket_history}"
    if jira_data:
        jira_sec = f"# Ticket {jira_data['id']} — información de Jira\n\n"
        jira_sec += f"**Resumen:** {jira_data['summary']}\n"
        if jira_data.get("status"):
            jira_sec += f"**Estado:** {jira_data['status']}"
        if jira_data.get("priority"):
            jira_sec += f"  |  **Prioridad:** {jira_data['priority']}"
        if jira_data.get("reporter"):
            jira_sec += f"  |  **Reportado por:** {jira_data['reporter']}"
        if jira_data.get("assignee"):
            jira_sec += f"  |  **Asignado a:** {jira_data['assignee']}"
        jira_sec += "\n"
        if jira_data.get("description"):
            jira_sec += f"\n## Descripción\n{jira_data['description']}\n"
        if jira_images:
            jira_sec += "\n## Evidencia adjunta (analizada)\n"
            for name, desc in jira_images:
                jira_sec += f"\n**{name}:**\n{desc}\n"
        if jira_excel:
            jira_sec += "\n## Archivos Excel adjuntos\n"
            for name, content in jira_excel:
                jira_sec += f"\n**{name}:**\n{content}\n"
        non_other = [
            a for a in (jira_data.get("attachments") or [])
            if not a.get("mimeType", "").startswith("image/")
            and "spreadsheet" not in a.get("mimeType", "")
            and "ms-excel" not in a.get("mimeType", "")
        ]
        if non_other:
            jira_sec += "\n## Otros adjuntos\n"
            for att in non_other:
                jira_sec += f"- {att.get('filename', '')} ({att.get('mimeType', '')})\n"
        content += f"\n\n---\n\n{jira_sec}"
    if brief:
        content += f"\n\n---\n\n# Plan de implementación\n\n{brief}"
    if image_description:
        content += f"\n\n---\n\n# Imagen de referencia\n\n{image_description}"
    if file:
        content += f"\n\n---\n\n# Archivo de entrada\n`{file}`"
    if task:
        content += f"\n\n---\n\n# Tarea\n{task}"
    from aicli.services.indexer import _write_md_atomic
    from aicli.services.tickets import save_session_ctx_path
    _write_md_atomic(ctx_path, content)
    save_session_ctx_path(str(ctx_path))

    # ── Título de terminal + mensaje inicial para Claude ─────────────────────
    import re
    tid = ticket_id or (re.search(r'[A-Z]+-\d+', task or "") or None) and \
          re.search(r'[A-Z]+-\d+', task or "").group()

    if tid and jira_data and jira_data.get("summary"):
        summary_short = jira_data["summary"][:50]
        tab_title = tid
        message = f"[{tid}] {summary_short} — Read {ctx_path} and start working on the task."
    elif tid:
        tab_title = tid
        message = f"[{tid}] Read {ctx_path} to get the project context and task, then start working."
    elif task:
        snippet = task.replace("\n", " ")[:40]
        tab_title = snippet[:28] + ("…" if len(task) > 28 else "")
        if question_mode:
            message = (
                f"Read {ctx_path} for full project context. "
                f"Then answer this question directly and concisely in Spanish: {task}"
            )
        else:
            message = f"Read {ctx_path} to get the project context and task, then start working."
    else:
        tab_title = "MAGNA"
        message = f"Read {ctx_path} to get the project context and task, then start working."

    _set_terminal_title(tab_title)

    is_windows = platform.system() == "Windows"
    claude_path = _find_claude_windows() if is_windows else None

    for attempt in range(2):
        try:
            if claude_path and is_windows:
                subprocess.run([str(claude_path), message], check=False, shell=False)
            else:
                subprocess.run(["claude", message], check=False, shell=is_windows)
            _set_terminal_title("MAGNA")
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