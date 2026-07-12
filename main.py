from dotenv import load_dotenv
from pathlib import Path
import os
import time
import logging

Path.home().joinpath(".mycontext").mkdir(exist_ok=True)
Path.home().joinpath(".mycontext", "evidencias").mkdir(exist_ok=True)
logging.basicConfig(
    filename=Path.home() / ".mycontext" / "aicli_log.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    encoding="utf-8",
)

load_dotenv()
load_dotenv(dotenv_path=Path.home() / ".mycontext" / ".env", override=False)

import typer
import questionary
from questionary import Style as QStyle
from rich.console import Console
from rich.rule import Rule
from aicli.commands import status, init, archive, file_cmd, sync, task, claude_cmd, proyecto
from aicli.db import init_db, engine

init_db()

app = typer.Typer(help="MAGNA — AI Context Engine")
app.add_typer(status.app,     name="status")
app.add_typer(init.app,       name="init")
app.add_typer(archive.app,    name="archive")
app.add_typer(file_cmd.app,   name="file")
app.add_typer(sync.app,       name="sync")
app.add_typer(task.app,       name="task")
app.add_typer(claude_cmd.app, name="claude")
app.add_typer(proyecto.app,   name="scan")

console = Console()

_ESTILO_SETUP = QStyle([
    ("qmark",       "fg:cyan bold"),
    ("question",    "fg:white bold"),
    ("pointer",     "fg:cyan bold"),
    ("highlighted", "fg:cyan bold"),
    ("selected",    "fg:cyan"),
    ("answer",      "fg:cyan bold"),
])


def _purge_evidence() -> None:
    folder = Path.home() / ".mycontext" / "evidencias"
    limit = time.time() - 7 * 86400
    for file in folder.iterdir():
        try:
            if file.is_file() and file.stat().st_mtime < limit:
                file.unlink()
        except Exception:
            pass


def _purge_session_contexts() -> None:
    folder = Path.home() / ".mycontext"
    limit = time.time() - 4 * 3600
    deleted = sum(
        1 for f in folder.glob("session_context_*.md")
        if f.stat().st_mtime < limit and not f.unlink()
    )
    if deleted:
        (folder / ".session_purge_notice").write_text(str(deleted), encoding="utf-8")


def _check_api_key() -> bool:
    if os.getenv("ANTHROPIC_API_KEY"):
        return True

    console.print()
    console.print(Rule(title="[bold cyan]Configuración inicial[/bold cyan]", style="cyan"))
    console.print()
    console.print("  MAGNA necesita tu [bold]API key de Anthropic[/bold] para funcionar.")
    console.print()
    console.print("  Conseguila en: [bold cyan]console.anthropic.com[/bold cyan] → API Keys")
    console.print()

    key = questionary.password("  Pegá tu ANTHROPIC_API_KEY", style=_ESTILO_SETUP).ask()

    if not key or not key.strip():
        console.print("\n[bold red]Error:[/bold red] La key no puede estar vacía.")
        return False

    key = key.strip()
    env_path = Path.home() / ".mycontext" / ".env"
    env_path.write_text(f"ANTHROPIC_API_KEY={key}\n", encoding="utf-8")
    os.environ["ANTHROPIC_API_KEY"] = key

    console.print()
    console.print(f"  [bold green]✔[/bold green] API key guardada en [dim]{env_path}[/dim]")
    console.print()
    return True


_purge_evidence()
_purge_session_contexts()


@app.callback(invoke_without_command=True)
def bienvenida(ctx: typer.Context):
    if ctx.invoked_subcommand is not None:
        return
    if not _check_api_key():
        raise typer.Exit(code=1)
    from aicli.tui.app import run_app
    run_app()


if __name__ == "__main__":
    app()
