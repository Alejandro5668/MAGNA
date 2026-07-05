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
from aicli.tui.theme import magna_warn, magna_error, ACCENT, SECTION, Q_STYLE_ARGS

app = typer.Typer()
console = Console()

_ESTILO = QStyle(Q_STYLE_ARGS)


def _read_review() -> str:
    console.print(f"  [{SECTION}]Pegá la revisión del PR. Enter dos veces para continuar.[/{SECTION}]\n")
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
        magna_error(console, "Este directorio no está registrado. Ejecutá ctx init primero.")
        return

    console.print()
    review_text = _read_review()

    if not review_text:
        magna_warn(console, "No se recibió texto.")
        return

    pr_num, ticket_id, criticals = _parse_review(review_text)

    if not criticals or "(Ninguno)" in criticals:
        console.print()
        console.print(Panel(
            Group(
                "[bold #4ADE80]✔ Sin problemas críticos[/bold #4ADE80]",
                f"[{SECTION}]El PR puede mergear.[/{SECTION}]",
            ),
            border_style="#4ADE80",
            padding=(1, 2),
        ))
        return

    review_files = _extract_files(criticals)
    pr_label = f"PR #{pr_num}" if pr_num else "PR"
    ticket_label = f" · {ticket_id}" if ticket_id else ""

    console.print()
    console.print(Panel(
        Text(criticals, style=f"{SECTION}"),
        title=f"[bold #F87171]🔴 {pr_label}{ticket_label}[/bold #F87171]",
        border_style="#F87171",
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
