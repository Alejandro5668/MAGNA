"""
Smoke tests para MAGNA — verifica imports, paleta y CLI tras el refactor.
Ejecutar: py tests/test_commands.py
No requiere API key ni proyecto registrado.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_PASS: list[str] = []
_FAIL: list[str] = []


def check(label: str, fn) -> None:
    try:
        fn()
        _PASS.append(label)
        print(f"  [OK]  {label}")
    except Exception as e:
        _FAIL.append(label)
        print(f"  [!!]  {label}")
        print(f"        {type(e).__name__}: {e}")


# ─── 1. Theme ─────────────────────────────────────────────────────────────────

def test_theme_palette():
    from aicli.tui.theme import (
        ACCENT, SECTION, BORDER, GLOW, ELEVATED, HOVER_BG,
        OK, WARN, ERROR, MID, MUTED, SEC,
        Q_STYLE_ARGS, SPINNER, SPINNER_STYLE,
    )
    assert ACCENT   == "#FFB703", f"ACCENT wrong: {ACCENT}"
    assert SECTION  == "#5B8DEF", f"SECTION wrong: {SECTION}"
    assert BORDER   == "#242C45", f"BORDER wrong: {BORDER}"
    assert OK       == "#4ADE80", f"OK wrong: {OK}"
    assert WARN     == "#FBBF24", f"WARN wrong: {WARN}"
    assert ERROR    == "#F87171", f"ERROR wrong: {ERROR}"
    assert SEC      == "#AAB4D4", f"SEC wrong: {SEC}"
    assert MUTED    == "#5E6A94", f"MUTED wrong: {MUTED}"
    assert isinstance(Q_STYLE_ARGS, list) and len(Q_STYLE_ARGS) > 0

check("theme: valores de paleta Noche Estrellada", test_theme_palette)


def test_theme_functions():
    from io import StringIO
    from rich.console import Console
    from aicli.tui.theme import (
        magna_ok, magna_warn, magna_error, magna_info,
        magna_panel, magna_task_plan, magna_table, magna_section,
        print_header, print_footer,
    )
    buf = Console(file=StringIO(), highlight=False)
    magna_ok(buf, "test ok")
    magna_warn(buf, "test warn")
    magna_error(buf, "test error")
    magna_info(buf, "test info")
    magna_panel(buf, "Panel", "contenido")
    magna_section(buf, "Sección")
    print_header(buf, "ctx test", "descripción")
    print_footer(buf)
    t = magna_table("Col A", "Col B")
    t.add_row("val1", "val2")
    # mock module list con atributo .name
    class _M:
        name = "TestModule"
    magna_task_plan(buf, [_M()], "1. Revisar archivo\n2. Actualizar lógica")

check("theme: funciones de output no lanzan excepciones", test_theme_functions)


# ─── 2. Imports de comandos ───────────────────────────────────────────────────

def test_cmd_init():
    from aicli.commands.init import init, detect_stack
    assert callable(init)
    assert callable(detect_stack)

check("cmd: init — importa correctamente", test_cmd_init)


def test_cmd_archive():
    from aicli.commands.archive import archive
    assert callable(archive)

check("cmd: archive — importa correctamente", test_cmd_archive)


def test_cmd_task():
    from aicli.commands.task import task, _execute_task, _detect_relevant_modules
    assert callable(task)
    assert callable(_execute_task)

check("cmd: task — importa correctamente", test_cmd_task)


def test_cmd_sync():
    from aicli.commands.sync import sync, _changed_files, _check_php_syntax
    assert callable(sync)
    assert callable(_changed_files)

check("cmd: sync — importa correctamente", test_cmd_sync)


def test_cmd_status():
    from aicli.commands.status import status
    assert callable(status)

check("cmd: status — importa correctamente", test_cmd_status)


def test_cmd_claude():
    from aicli.commands.claude_cmd import claude
    assert callable(claude)

check("cmd: claude — importa correctamente", test_cmd_claude)


def test_cmd_proyecto():
    from aicli.commands.proyecto import proyecto
    assert callable(proyecto)

check("cmd: proyecto/scan — importa correctamente", test_cmd_proyecto)


def test_cmd_file():
    from aicli.commands.file_cmd import file_cmd, _save_zone_modules
    assert callable(file_cmd)

check("cmd: file_cmd — importa correctamente", test_cmd_file)


# ─── 3. TUI ───────────────────────────────────────────────────────────────────

def test_tui_imports():
    from aicli.tui.app import (
        MagnaApp, MainScreen, ProjectScreen, StatusScreen,
        OnboardingScreen, InputModal, CommandScreen, HelpScreen,
        _MENU, _HELP_ROWS, _cmd_desc, _menu_option, _DESC_MAX,
        _ACCENT, _SECTION, _BORDER, _OK, _MUTED, _SEC,
        _gradient_logo,
    )
    assert _ACCENT == "#FFB703"
    assert _OK     == "#4ADE80"
    assert _MUTED  == "#5E6A94"
    assert _SEC    == "#AAB4D4"
    assert len(_MENU) == 3
    assert _cmd_desc("task") == "Claude task context"
    # gradient logo devuelve un Rich Text con contenido
    from rich.text import Text
    logo = _gradient_logo()
    assert isinstance(logo, Text)
    assert len(logo) > 0
    # ProjectScreen usa Static + reactive cursor (sin ListView)
    import inspect
    src_animate = inspect.getsource(ProjectScreen._animate_entry)
    assert "animate" in src_animate, "_animate_entry debe usar animate()"
    assert "opacity" in src_animate, "_animate_entry debe animar opacity"
    assert 'animate("offset"' not in src_animate, "offset no es animable en Textual 8.x"
    src_screen = inspect.getsource(ProjectScreen)
    assert "ListView" not in src_screen, "ProjectScreen no debe usar ListView — usa Static + reactive"
    assert "_cursor" in src_screen, "ProjectScreen debe tener reactive _cursor"
    assert "_render_list" in src_screen, "ProjectScreen debe tener _render_list()"

check("tui: app.py — imports y constantes de paleta", test_tui_imports)


def test_tui_menu_no_wrap():
    from aicli.tui.app import _MENU, _menu_option, _DESC_MAX
    for section, items in _MENU:
        for key, name, desc in items:
            opt = _menu_option(key, name, desc)
            # La descripción final no debe exceder _DESC_MAX
            assert len(desc) <= _DESC_MAX, (
                f"'{name}' desc too long ({len(desc)} > {_DESC_MAX}): '{desc}'"
            )

check("tui: todas las descripciones del menú caben en una línea", test_tui_menu_no_wrap)


def test_tui_help_rows():
    from aicli.tui.app import _HELP_ROWS
    assert len(_HELP_ROWS) >= 9
    keys = [row[0] for row in _HELP_ROWS]
    assert "?" in keys
    assert "q" in keys
    assert "g" in keys

check("tui: help overlay tiene todos los keybindings", test_tui_help_rows)


# ─── 4. DB ────────────────────────────────────────────────────────────────────

def test_db_engine():
    from aicli.db import engine
    from aicli.db.models import Project, Module, Activity
    assert engine is not None

check("db: engine e models importan sin error", test_db_engine)


def test_db_init():
    from aicli.db import init_db
    init_db()  # idempotente — no debe explotar si ya existe

check("db: init_db() es idempotente", test_db_init)


# ─── 5. Services ──────────────────────────────────────────────────────────────

def test_services():
    from aicli.services.builder import build_context
    from aicli.services.caller import launch_claude
    from aicli.services.activity import log_activity
    from aicli.services.indexer import NON_CODE_EXTENSIONS, get_tree
    assert callable(build_context)
    assert callable(launch_claude)
    assert callable(log_activity)
    assert callable(get_tree)
    assert isinstance(NON_CODE_EXTENSIONS, (set, frozenset))

check("services: builder, caller, activity, indexer importan", test_services)


def test_activity_log():
    from aicli.services.activity import log_activity
    # No debe explotar — registra silenciosamente si no hay proyecto
    log_activity("test_smoke")

check("services: log_activity() no lanza excepción", test_activity_log)


# ─── 6. CLI registration ──────────────────────────────────────────────────────

def test_cli_help():
    from typer.testing import CliRunner
    sys.argv = ["ctx"]
    import importlib, main as m
    importlib.reload(m)
    runner = CliRunner()
    result = runner.invoke(m.app, ["--help"])
    assert result.exit_code == 0
    output = result.output
    for cmd in ("init", "archive", "task", "sync", "status", "claude", "scan", "file"):
        assert cmd in output, f"comando '{cmd}' no aparece en --help"

check("cli: ctx --help muestra todos los comandos registrados", test_cli_help)


def test_cli_init_help():
    from typer.testing import CliRunner
    import main as m
    runner = CliRunner()
    result = runner.invoke(m.app, ["init", "--help"])
    assert result.exit_code == 0

check("cli: ctx init --help responde sin error", test_cli_init_help)


def test_cli_status_no_project():
    from typer.testing import CliRunner
    import main as m
    import os, tempfile
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmp:
        old = os.getcwd()
        os.chdir(tmp)
        result = runner.invoke(m.app, ["status"])
        os.chdir(old)
    # Debe salir limpiamente (código 0 o 1 con mensaje, no excepción)
    assert result.exit_code in (0, 1)
    assert result.exception is None or "registrado" in str(result.output)

check("cli: ctx status en directorio sin proyecto sale limpiamente", test_cli_status_no_project)


def test_no_asyncio_run_in_dispatch():
    """_dispatch_tui no llama asyncio.run() directamente — usa inyección de consola."""
    import inspect
    from aicli.tui import app as tui_app
    src = inspect.getsource(tui_app._dispatch_tui)
    assert "asyncio.run(" not in src, "_dispatch_tui llama asyncio.run() directamente"
    assert "TuiConsole" in src or "tui_console" in src, "_dispatch_tui debe recibir TuiConsole"

check("tui: _dispatch_tui no llama asyncio.run() y usa TuiConsole", test_no_asyncio_run_in_dispatch)


def test_output_screen_integration():
    """CommandOutputScreen y TuiConsole importan y tienen la interfaz correcta."""
    from aicli.tui.output_screen import CommandOutputScreen, TuiConsole
    from aicli.tui import app as tui_app
    import inspect
    # TuiConsole tiene los métodos clave
    assert callable(getattr(TuiConsole, "print", None))
    assert callable(getattr(TuiConsole, "status", None))
    assert callable(getattr(TuiConsole, "suspend_and_run", None))
    assert callable(getattr(TuiConsole, "request_input", None))
    assert callable(getattr(TuiConsole, "request_confirm", None))
    # _worker_cmd usa CommandOutputScreen + run_in_executor
    src = inspect.getsource(tui_app.MainScreen._worker_cmd)
    assert "CommandOutputScreen" in src
    assert "run_in_executor" in src

check("tui: CommandOutputScreen + TuiConsole integrados en _worker_cmd", test_output_screen_integration)


def test_no_active_app_context_bug():
    """
    request_input/confirm no deben usar asyncio.run_coroutine_threadsafe directamente.
    Ese método copia el contexto del thread (sin _active_app) y causa NoActiveAppError
    al componer modales. El fix es _run_on_loop con call_soon_threadsafe(context=_ctx).
    """
    import inspect
    from aicli.tui.output_screen import CommandOutputScreen
    from aicli.tui import app as tui_app

    src_screen = inspect.getsource(CommandOutputScreen)
    # _run_on_loop debe existir y usar call_soon_threadsafe con context
    assert "_run_on_loop" in src_screen, "CommandOutputScreen debe tener _run_on_loop"
    assert "call_soon_threadsafe" in src_screen, "_run_on_loop debe usar call_soon_threadsafe"
    assert "context=self._ctx" in src_screen, "_run_on_loop debe pasar context=self._ctx"
    # request_input y request_confirm no deben llamar run_coroutine_threadsafe directamente
    src_input   = inspect.getsource(CommandOutputScreen.request_input)
    src_confirm = inspect.getsource(CommandOutputScreen.request_confirm)
    assert "run_coroutine_threadsafe" not in src_input,   "request_input no debe usar run_coroutine_threadsafe"
    assert "run_coroutine_threadsafe" not in src_confirm, "request_confirm no debe usar run_coroutine_threadsafe"
    # _worker_cmd debe capturar el contexto antes del thread
    src_worker = inspect.getsource(tui_app.MainScreen._worker_cmd)
    assert "copy_context" in src_worker, "_worker_cmd debe capturar contextvars.copy_context() antes del thread"
    assert "_ctx" in src_worker, "_worker_cmd debe asignar _ctx al out_screen"

check("tui: contexto Textual propagado correctamente a modales desde thread", test_no_active_app_context_bug)


# ─── Resultados ───────────────────────────────────────────────────────────────

print()
print("  " + "-" * 44)
total = len(_PASS) + len(_FAIL)
print(f"  {len(_PASS)}/{total} pasaron", end="")
if _FAIL:
    print(f"  |  {len(_FAIL)} fallaron")
    print()
    for f in _FAIL:
        print(f"    - {f}")
    sys.exit(1)
else:
    print("  -- todo ok")
