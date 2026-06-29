import re
import typer
import questionary
from pathlib import Path
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text
from questionary import Style as QStyle
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project, Module
from aicli.services.builder import build_context
from aicli.services.caller import launch_claude
from aicli.services.tickets import load_tickets, format_history

app = typer.Typer()
console = Console()

_ESTILO = QStyle([
    ("qmark",       "fg:cyan bold"),
    ("question",    "fg:white bold"),
    ("pointer",     "fg:cyan bold"),
    ("highlighted", "fg:cyan bold"),
    ("selected",    "fg:cyan"),
    ("answer",      "fg:cyan bold"),
])


def _read_review() -> str:
    console.print("  [dim]Pegá la revisión del PR. Enter dos veces para continuar.[/dim]\n")
    lines = []
    empty_count = 0
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "":
            empty_count += 1
            if empty_count >= 2:
                break
            lines.append(line)
        else:
            empty_count = 0
            lines.append(line)
    return "\n".join(lines).strip()


def _parse_review(text: str) -> tuple[str, str, str]:
    """Extrae (pr_num, ticket_id, texto_criticos) del review."""
    pr_match = re.search(r'PR #(\d+)', text)
    ticket_match = re.search(r'\[([A-Z]+-\d+)\]', text)
    pr_num = pr_match.group(1) if pr_match else ""
    ticket_id = ticket_match.group(1) if ticket_match else ""

    parts = re.split(r'(?=🟡|🟢)', text, maxsplit=1)
    red_block = parts[0]
    match = re.search(r'🔴[^\n]*\n(.*)', red_block, re.DOTALL)
    criticals = match.group(1).strip() if match else ""

    return pr_num, ticket_id, criticals


def _extract_files(text: str) -> list[str]:
    pattern = r'[\w/]+\.(?:php|js|ts|vue|py|java|cs)\b'
    return list(set(re.findall(pattern, text)))


@app.callback(invoke_without_command=True)
def revision():
    """Procesa revisión de PR y lanza Claude para resolver los críticos."""
    path = Path.cwd()

    with Session(engine) as session:
        project = session.exec(select(Project).where(Project.path == str(path))).first()

    if not project:
        console.print("[bold red]Error:[/bold red] Este directorio no está registrado. Ejecutá [bold]ctx init[/bold] primero.")
        return

    console.print()
    review_text = _read_review()

    if not review_text:
        console.print("  [bold yellow]⚠[/bold yellow] [dim]No se recibió texto.[/dim]")
        return

    pr_num, ticket_id, criticals = _parse_review(review_text)

    if not criticals or "(Ninguno)" in criticals:
        console.print()
        console.print(Panel(
            Group(
                "[bold green]✔ Sin problemas críticos[/bold green]",
                "[dim]El PR puede mergear.[/dim]",
            ),
            border_style="green",
            padding=(1, 2),
        ))
        return

    review_files = _extract_files(criticals)
    pr_label = f"PR #{pr_num}" if pr_num else "PR"
    ticket_label = f" · {ticket_id}" if ticket_id else ""

    console.print()
    console.print(Panel(
        Text(criticals, style="dim"),
        title=f"[bold red]🔴 {pr_label}{ticket_label}[/bold red]",
        border_style="red",
        padding=(1, 2),
    ))

    # Historial del ticket si existe en memoria
    history = ""
    if ticket_id:
        tickets = load_tickets()
        history = format_history(ticket_id, tickets) or ""

    # Módulos documentados que coincidan con los archivos del review
    with Session(engine) as session:
        all_modules = list(session.exec(select(Module).where(Module.project_id == project.id)).all())

    affected_modules = []
    if review_files:
        for file in review_files:
            for m in all_modules:
                if file in m.file_path or m.file_path.endswith(file):
                    if m not in affected_modules:
                        affected_modules.append(m)

    context = build_context(affected_modules)

    task_desc = f"[REVISIÓN {pr_label}{ticket_label} — CRÍTICOS A RESOLVER]\n\n{criticals}"
    if review_files:
        task_desc += f"\n\nArchivos mencionados: {', '.join(review_files)}"

    launch_claude(
        context=context,
        task=task_desc,
        ticket_history=history or None,
    )
