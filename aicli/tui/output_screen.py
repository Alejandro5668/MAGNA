"""
CommandOutputScreen — ejecuta comandos dentro de la TUI sin suspend.
TuiConsole — enruta print/status al RichLog vía call_from_thread.
"""
from __future__ import annotations
import asyncio
from contextlib import contextmanager

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static, Rule, RichLog, LoadingIndicator

_ACCENT  = "#FFB703"
_SECTION = "#5B8DEF"
_BORDER  = "#242C45"
_OK      = "#4ADE80"
_WARN    = "#FBBF24"
_ERROR   = "#F87171"
_SEC     = "#AAB4D4"
_MUTED   = "#5E6A94"


class CommandOutputScreen(ModalScreen[None]):
    """Muestra el output de un comando en tiempo real. Reemplaza suspend()."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("q",      "go_back", show=False),
    ]

    DEFAULT_CSS = f"""
    CommandOutputScreen {{
        background: #000000;
    }}
    #co-frame {{
        width: 100%;
        height: 100%;
        background: #000000;
        layout: vertical;
    }}
    #co-title {{
        color: {_SEC};
        text-align: center;
        height: 1;
        padding: 1 0 0 0;
    }}
    Rule {{
        color: {_BORDER};
        margin: 0;
    }}
    #co-spinner {{
        height: 1;
        margin: 1 2 0 2;
    }}
    #co-log {{
        background: transparent;
        border: none;
        padding: 0 2;
        height: 1fr;
    }}
    #co-done {{
        text-align: right;
        padding: 0 2 1 2;
        height: 2;
    }}
    """

    def __init__(self, command: str, description: str) -> None:
        super().__init__()
        self._command = command
        self._description = description
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ctx = None  # contextvars.Context capturado en el event loop antes del thread

    def compose(self) -> ComposeResult:
        with Container(id="co-frame"):
            yield Static(
                f"[bold {_ACCENT}]ctx {self._command}[/bold {_ACCENT}]"
                f"  [{_SEC}]{self._description}[/{_SEC}]",
                id="co-title", markup=True,
            )
            yield Rule(line_style="heavy")
            yield LoadingIndicator(id="co-spinner")
            yield RichLog(markup=False, highlight=False, wrap=True, id="co-log")
            yield Static("", id="co-done")

    # ── Output ────────────────────────────────────────────────────────────────

    def write_line(self, content) -> None:
        """Append content to RichLog. Call via app.call_from_thread()."""
        try:
            self.query_one("#co-log", RichLog).write(content)
        except Exception:
            pass

    def mark_done(self) -> None:
        """Hide spinner, show hint. Call from async context after thread ends."""
        try:
            self.query_one("#co-spinner", LoadingIndicator).display = False
            self.query_one("#co-done", Static).update(
                f"[{_MUTED}]──[/{_MUTED}]  [bold {_ACCENT}]esc[/bold {_ACCENT}]"
                f"  [{_SEC}]volver[/{_SEC}]"
            )
        except Exception:
            pass

    # ── Suspend bridge (for Claude launch) ───────────────────────────────────

    async def _run_in_suspend(self, fn) -> None:
        with self.app.suspend():
            fn()

    def suspend_and_run(self, fn) -> None:
        """Block caller thread while TUI suspends and fn() runs."""
        if self._loop is None:
            fn()
            return
        self._run_on_loop(self._run_in_suspend(fn))

    # ── Context-aware scheduler ───────────────────────────────────────────────

    def _run_on_loop(self, coro):
        """Schedule coro on the event loop in the app's ContextVar context and block.

        run_coroutine_threadsafe copies the CALLING THREAD's context, which lacks
        Textual's _active_app ContextVar. Passing _ctx explicitly fixes NoActiveAppError
        when push_screen_wait composes a new modal screen.
        """
        import concurrent.futures
        fut = concurrent.futures.Future()

        def _run():
            task = asyncio.ensure_future(coro)
            def _on_done(t: asyncio.Task):
                if t.cancelled():
                    fut.cancel()
                elif t.exception():
                    fut.set_exception(t.exception())
                else:
                    fut.set_result(t.result())
            task.add_done_callback(_on_done)

        self._loop.call_soon_threadsafe(_run, context=self._ctx)
        return fut.result()

    # ── Input bridge ──────────────────────────────────────────────────────────

    async def _push_input(self, prompt: str, placeholder: str) -> str | None:
        from aicli.tui.app import InputModal
        return await self.app.push_screen_wait(InputModal(prompt, placeholder))

    def request_input(self, prompt: str, placeholder: str = "") -> str | None:
        """Block caller thread until user responds to an InputModal."""
        if self._loop is None:
            return input(f"  {prompt}: ").strip() or None
        return self._run_on_loop(self._push_input(prompt, placeholder))

    async def _push_confirm(self, prompt: str, default: bool) -> bool:
        from aicli.tui.app import ConfirmModal
        return await self.app.push_screen_wait(ConfirmModal(prompt, default))

    def request_confirm(self, prompt: str, default: bool = True) -> bool:
        """Block caller thread until user responds to a Yes/No modal."""
        if self._loop is None:
            resp = input(f"  {prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
            return resp not in ("n", "no") if default else resp in ("y", "si", "sí", "yes")
        return self._run_on_loop(self._push_confirm(prompt, default))

    def action_go_back(self) -> None:
        self.dismiss(None)


# ─── TuiConsole ───────────────────────────────────────────────────────────────

class TuiConsole:
    """
    Drop-in para Rich Console durante la ejecución de comandos.
    Enruta print/status/input al CommandOutputScreen activo.
    """

    def __init__(self, screen: CommandOutputScreen) -> None:
        self._screen = screen

    def print(self, *args, markup: bool = True, end: str = "\n", **kwargs) -> None:
        if not args:
            return
        content = args[0] if len(args) == 1 else " ".join(str(a) for a in args)
        if isinstance(content, str):
            try:
                rendered: object = Text.from_markup(content) if markup else Text(content)
            except Exception:
                rendered = Text(str(content))
        else:
            rendered = content  # Panel, Group, Rule, etc.
        self._screen.app.call_from_thread(self._screen.write_line, rendered)

    @contextmanager
    def status(self, message: str, spinner: str = "dots3",
               spinner_style: str = _ACCENT, **kwargs):
        """Muestra un mensaje de progreso en el log (el spinner lo maneja LoadingIndicator)."""
        self.print(f"[{_ACCENT}]◆  {message}[/{_ACCENT}]")
        try:
            yield self
        finally:
            pass

    # ── Bridges ───────────────────────────────────────────────────────────────

    def suspend_and_run(self, fn) -> None:
        self._screen.suspend_and_run(fn)

    def request_input(self, prompt: str, placeholder: str = "") -> str | None:
        return self._screen.request_input(prompt, placeholder)

    def request_confirm(self, prompt: str, default: bool = True) -> bool:
        return self._screen.request_confirm(prompt, default)
