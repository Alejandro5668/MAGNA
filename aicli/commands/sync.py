import typer
import subprocess
import time
import json
import questionary
from datetime import datetime
from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from pathlib import Path
from questionary import Style as QStyle
from sqlmodel import Session, select
from aicli.db import engine
from aicli.db.models import Project, Module, ModuleLesson
from aicli.services.indexer import analyze_file_deep, generate_case_summary, NON_CODE_EXTENSIONS, _write_md_atomic
from aicli.services.tickets import load_tickets, save_round, format_history, read_active_ticket, clear_active_ticket
from aicli.tui.theme import (
    magna_ok, magna_warn, magna_error, magna_info, magna_status, magna_panel,
    ACCENT, SECTION, BORDER, Q_STYLE_ARGS,
)

app = typer.Typer()
console = Console()

_ESTILO = QStyle(Q_STYLE_ARGS)


def _show_case_card(ticket_id: str, round_num: int, files: set[str], case_memory: dict) -> None:
    files_txt = "\n".join(f"  · {a}" for a in sorted(files))
    pasos_qa = case_memory.get("pasos_qa", "")

    items = [
        Text.from_markup(f"[{SECTION}]{files_txt}[/{SECTION}]"),
        Rule(style=BORDER),
        Text(""),
        Text.from_markup("[bold #F1F3F9]  Investigado[/bold #F1F3F9]"),
        Text.from_markup(f"[{SECTION}]  {case_memory['investigado']}[/{SECTION}]"),
        Text(""),
        Text.from_markup(f"[bold #4ADE80]  Hecho[/bold #4ADE80]"),
        Text.from_markup(f"[{SECTION}]  {case_memory['hecho']}[/{SECTION}]"),
        Text(""),
        Text.from_markup(f"[bold #FBBF24]  Tener en cuenta[/bold #FBBF24]"),
        Text.from_markup(f"[{SECTION}]  {case_memory['tener_en_cuenta']}[/{SECTION}]"),
        Text(""),
    ]
    if pasos_qa:
        items += [
            Rule(style=BORDER),
            Text(""),
            Text.from_markup(f"[bold {ACCENT}]  Pasos para QA[/bold {ACCENT}]"),
            Text.from_markup(f"[{SECTION}]  {pasos_qa}[/{SECTION}]"),
            Text(""),
        ]

    console.print(Panel(
        Group(*items),
        title=f"[bold {ACCENT}] {ticket_id} [/bold {ACCENT}][{SECTION}]· Ronda {round_num}[/{SECTION}]",
        border_style=ACCENT,
        padding=(1, 2),
    ))


def _read_session_task() -> str:
    """Lee la tarea del session_context más reciente generado por ctx task."""
    ctx_dir = Path.home() / ".mycontext"
    ctx_files = sorted(ctx_dir.glob("session_context_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not ctx_files:
        return ""
    content = ctx_files[0].read_text(encoding="utf-8")
    if "# Tarea" not in content:
        return ""
    return content.split("# Tarea")[-1].strip()


def _get_diff(path: Path, files: list[str]) -> str:
    """Obtiene el git diff de los archivos cambiados. Prioriza uncommitted, luego último commit."""
    file_args = ["--"] + files
    for cmd in [
        ["git", "diff", "HEAD"] + file_args,
        ["git", "diff", "HEAD~1"] + file_args,
    ]:
        try:
            result = subprocess.run(
                cmd, cwd=str(path), capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout
        except Exception:
            continue
    return ""


def _changed_files(path: Path) -> set[str]:
    """Uncommitted primero; solo si no hay nada, mira el último commit."""
    def _run(cmd: list[str]) -> set[str]:
        try:
            r = subprocess.run(cmd, cwd=str(path), capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                return {
                    l.strip() for l in r.stdout.splitlines()
                    if l.strip() and Path(l.strip()).suffix not in NON_CODE_EXTENSIONS
                }
        except Exception:
            pass
        return set()

    changed = _run(["git", "diff", "HEAD", "--name-only"])
    changed |= _run(["git", "diff", "--cached", "--name-only"])

    if not changed:
        changed = _run(["git", "diff", "HEAD~1", "--name-only"])

    return changed


def _check_php_syntax(path: Path, files: set[str]) -> list[str]:
    errors = []
    for file in sorted(files):
        if not file.endswith(".php"):
            continue
        try:
            r = subprocess.run(
                ["php", "-l", str(path / file)],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode != 0:
                msg = (r.stderr or r.stdout).strip().splitlines()[0]
                errors.append(f"{file}: {msg}")
        except FileNotFoundError:
            break  # php no instalado — saltar silenciosamente
        except Exception:
            continue
    return errors



@app.callback(invoke_without_command=True)
def sync():
    """Detecta archivos cambiados con git y actualiza su documentación."""
    _sync_impl()


def _sync_impl(ask_fn=None, confirm_fn=None):
    """Lógica real de sync. ask_fn/confirm_fn permiten sustituir questionary desde la TUI."""
    from aicli.services.activity import log_activity
    log_activity("sync")
    path = Path.cwd()

    with Session(engine) as session:
        project = session.exec(select(Project).where(Project.path == str(path))).first()

    if not project:
        magna_error(console, "Este directorio no está registrado. Ejecutá ctx init primero.")
        raise typer.Exit(code=1)

    with magna_status(console, "Detectando archivos cambiados..."):
        changed = _changed_files(path)

    existing_files = {f for f in changed if (path / f).exists()}

    if not existing_files:
        magna_warn(console, "Sin cambios detectados. No hay archivos modificados en git.")
        return

    console.print(f"\n[bold {ACCENT}]{len(existing_files)} archivos cambiados detectados[/bold {ACCENT}]")

    syntax_errors = _check_php_syntax(path, existing_files)
    if syntax_errors:
        console.print()
        for e in syntax_errors:
            magna_error(console, e)
        console.print(f"\n  [bold #F87171]Errores de sintaxis PHP. Corregí antes de continuar.[/bold #F87171]")
        return

    with Session(engine) as session:
        modules_db = list(session.exec(select(Module).where(Module.project_id == project.id)).all())

    modules_by_path = {m.file_path: m for m in modules_db}

    updated = 0
    new_count = 0
    base = Path.home() / ".mycontext" / "projects" / str(project.id)

    for file_path in sorted(existing_files):
        magna_info(console, f"Documentando {file_path}...")

        md_file = base / Path(file_path).with_suffix(".md")
        existing_doc = md_file.read_text(encoding="utf-8") if md_file.exists() else ""
        file_diff = _get_diff(path, [file_path])

        try:
            content_md, tokens = analyze_file_deep(
                path, file_path, project.name, project.stack or "desconocido",
                diff=file_diff,
                existing_doc=existing_doc,
            )
        except Exception as e:
            magna_warn(console, f"{file_path} — falló: {e}")
            continue

        md_file.parent.mkdir(parents=True, exist_ok=True)
        _write_md_atomic(md_file, content_md)

        name = Path(file_path).stem
        description = next((l.lstrip("# ") for l in content_md.splitlines() if l.strip()), name)

        with Session(engine) as session:
            existing = modules_by_path.get(file_path)
            if existing:
                m = session.get(Module, existing.id)
                m.content_path = str(md_file)
                m.last_updated_at = time.time()
                session.add(m)
                session.commit()
                updated += 1
            else:
                session.add(Module(
                    project_id=project.id,
                    name=name,
                    description=description,
                    file_path=file_path,
                    content_path=str(md_file),
                    created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    last_updated_at=time.time(),
                ))
                session.commit()
                new_count += 1

        magna_ok(console, f"{file_path} · {tokens:,} tokens")

    # Captura de decisión técnica post-tarea
    console.print()
    if ask_fn:
        decision = ask_fn("¿Hubo alguna decisión técnica importante? (Enter para omitir)")
    else:
        decision = questionary.text(
            "  ¿Hubo alguna decisión técnica importante? (Enter para omitir)",
            style=_ESTILO,
        ).ask()

    if decision and decision.strip():
        decisions_path = Path.home() / ".mycontext" / "projects" / str(project.id) / "decisions.md"
        date = datetime.now().strftime("%Y-%m-%d")
        entry = f"## {date}\n\n{decision.strip()}\n\n---\n\n"
        if decisions_path.exists():
            decisions_path.write_text(entry + decisions_path.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            decisions_path.write_text(f"# Decisiones técnicas del proyecto\n\n{entry}", encoding="utf-8")
        magna_ok(console, f"Decisión guardada en {decisions_path}")

    # Generar resumen del caso (Jira + memoria) en una sola llamada
    original_task = _read_session_task()
    full_diff = _get_diff(path, list(existing_files))
    active_ticket = read_active_ticket()
    ticket_prefill = active_ticket["ticket_id"] if active_ticket else ""
    reason_prefill = active_ticket.get("motivo_reapertura") if active_ticket else None

    jira_msg: str | None = None
    case_memory: dict | None = None

    if original_task:
        previous_history = ""
        if active_ticket:
            prev_tid = active_ticket.get("ticket_id", "")
            if prev_tid:
                previous_history = format_history(prev_tid, load_tickets()) or ""

        console.print()
        with magna_status(console, "Generando resumen del caso..."):
            try:
                jira_msg, case_memory, tokens_res = generate_case_summary(
                    original_task, full_diff, list(existing_files), previous_history
                )
            except Exception as e:
                magna_warn(console, f"No se pudo generar el resumen: {e}")

        if jira_msg:
            pasos_qa = case_memory.get("pasos_qa", "") if case_memory else ""
            full_msg = jira_msg
            if pasos_qa:
                full_msg += f"\n\nPasos para QA:\n{pasos_qa}"

            panel_body = Group(
                Text.from_markup(jira_msg),
                *(
                    [
                        Text(""),
                        Rule(style=BORDER),
                        Text.from_markup(f"[bold {SECTION}]Pasos para QA[/bold {SECTION}]"),
                        Text.from_markup(f"[{SECTION}]{pasos_qa}[/{SECTION}]"),
                    ]
                    if pasos_qa else []
                ),
            )
            console.print(Panel(
                panel_body,
                title=f"[bold {ACCENT}]Mensaje de Jira[/bold {ACCENT}]",
                border_style=ACCENT,
                padding=(1, 2),
            ))

            # Auto-copiar al portapapeles de Windows
            try:
                import subprocess as _sp
                _sp.run("clip", input=full_msg.encode("utf-16le"), check=False, shell=True)
                magna_ok(console, f"{tokens_res:,} tokens · copiado al portapapeles")
            except Exception:
                magna_info(console, f"{tokens_res:,} tokens")
    else:
        console.print()
        magna_warn(console, "Sin tarea de sesión — ejecutá ctx task antes de sync para generar el resumen.")

    console.print()
    console.print(Panel(
        Group(
            f"[bold #4ADE80]✔ Sync completado[/bold #4ADE80]",
            f"[{SECTION}]Actualizados: {updated}  |  Nuevos: {new_count}[/{SECTION}]",
        ),
        title="ctx sync",
        border_style="#4ADE80",
    ))

    # Guardar caso en historial
    console.print()
    if ask_fn:
        ticket_id_raw = ask_fn(
            f"¿Número de ticket Jira? (Enter para omitir)",
            ticket_prefill,
        )
    else:
        ticket_id_raw = questionary.text(
            "  ¿Número de ticket Jira? (Enter para omitir)",
            default=ticket_prefill,
            style=_ESTILO,
        ).ask()

    if ticket_id_raw and ticket_id_raw.strip():
        ticket_id = ticket_id_raw.strip().upper()
        current_tickets = load_tickets()
        round_num = len(current_tickets.get(ticket_id, {}).get("rondas", [])) + 1

        if case_memory:
            console.print()
            _show_case_card(ticket_id, round_num, existing_files, case_memory)

            console.print()
            if ask_fn:
                addition = ask_fn("¿Algo más para 'Tener en cuenta'? (Enter para aceptar)")
            else:
                addition = questionary.text(
                    "  ¿Algo más para 'Tener en cuenta'? (Enter para aceptar)",
                    style=_ESTILO,
                ).ask()
            if addition and addition.strip():
                case_memory["tener_en_cuenta"] += " " + addition.strip()
                console.print()
                _show_case_card(ticket_id, round_num, existing_files, case_memory)

        console.print()
        if confirm_fn:
            save = confirm_fn("¿Guardar este caso?", True)
        else:
            save = questionary.confirm(
                "  ¿Guardar este caso?",
                default=True,
                style=_ESTILO,
            ).ask()

        if save:
            if ticket_id in current_tickets:
                description = current_tickets[ticket_id]["descripcion"]
            else:
                description = original_task or ticket_id

            save_round(
                ticket_id=ticket_id,
                description=description,
                archivos_tocados=list(existing_files),
                mensaje_jira=jira_msg,
                motivo_reapertura=reason_prefill,
                memoria=case_memory,
            )

            # Persistir lecciones por módulo tocado
            if case_memory:
                lesson_text = case_memory.get("tener_en_cuenta", "").strip()
                if lesson_text:
                    date_str = datetime.now().strftime("%Y-%m-%d")
                    with Session(engine) as session:
                        for fp in existing_files:
                            session.add(ModuleLesson(
                                project_id=project.id,
                                file_path=fp,
                                ticket_id=ticket_id,
                                date=date_str,
                                lesson=lesson_text,
                                lesson_type="gotcha",
                            ))
                        session.commit()

            clear_active_ticket()
            magna_ok(console, f"Ronda {round_num} guardada para {ticket_id}")

