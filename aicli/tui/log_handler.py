"""
TuiLogHandler — routes WARNING+ log records to the active CommandOutputScreen.

Register once at startup; activate per-command via set_screen/clear_screen.
"""
import logging
from rich.text import Text

_WARN  = "#FBBF24"
_ERROR = "#F87171"


class TuiLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self._screen = None
        self.setFormatter(logging.Formatter("%(levelname)s — %(name)s — %(message)s"))

    def set_screen(self, screen) -> None:
        self._screen = screen

    def clear_screen(self) -> None:
        self._screen = None

    def emit(self, record: logging.LogRecord) -> None:
        if self._screen is None:
            return
        try:
            msg = self.format(record)
            color = _ERROR if record.levelno >= logging.ERROR else _WARN
            self._screen.app.call_from_thread(
                self._screen.write_line, Text(msg, style=color)
            )
        except Exception:
            pass


tui_handler = TuiLogHandler()
