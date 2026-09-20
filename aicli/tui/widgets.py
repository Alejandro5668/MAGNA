from __future__ import annotations

import logging

from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static, Rule
from textual.containers import VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual import work

# ─── Noche Estrellada — mirrors theme.py ──────────────────────────────────────
_ACCENT   = "#FFB703"
_SECTION  = "#5B8DEF"
_BORDER   = "#242C45"
_BORDER_A = "#3A4468"
_GLOW     = "#E8A20A"
_ELEVATED = "#0D1120"
_HOVER    = "#161d33"
_SELECT   = "#4A3D1A"
_OK       = "#4ADE80"
_WARN     = "#FBBF24"
_ERROR    = "#F87171"
_MID      = "#3A4468"
_SEC      = "#AAB4D4"
_MUTED    = "#5E6A94"

# ─── Ticket Panel ─────────────────────────────────────────────────────────────

_PRIO_ORDER = {
    "Critical": 0, "Crítica": 0, "Highest": 0,
    "High": 1, "Alta": 1,
    "Medium": 2, "Media": 2,
    "Low": 3, "Baja": 3, "Lowest": 4,
}
_PRIO_BADGE = {
    "Critical": ("!", _ERROR), "Crítica": ("!", _ERROR), "Highest": ("!", _ERROR),
    "High": ("▲", _WARN),  "Alta": ("▲", _WARN),
    "Medium": ("·", _SEC), "Media": ("·", _SEC),
    "Low": ("▽", _MUTED),  "Baja": ("▽", _MUTED), "Lowest": ("▽", _MUTED),
}

_DONE_WORDS = {"done", "cerrado", "cerrada", "resuelto", "resuelta", "completado", "completada"}
_BLOCKED_WORDS = {"blocked", "bloqueado", "bloqueada", "impedimento"}
_CURRENT_WORDS = {"in progress", "en curso", "en progreso", "doing", "review", "revisión", "revision", "testing", "qa"}

_CHIP_GLYPH = {
    "done": ("✓", _OK),
    "current": ("●", _ACCENT),
    "blocked": ("✕", _ERROR),
    "todo": ("○", _MUTED),
}


def _chip_state(status: str) -> str:
    """Mapea el texto de estado de Jira a uno de los 4 estados visuales del
    chip (done/current/todo/blocked). Heurística por substring — no hay
    statusCategory disponible en fetch_subtasks."""
    s = (status or "").strip().lower()
    if s in _BLOCKED_WORDS or "bloque" in s or "impedim" in s:
        return "blocked"
    if s in _DONE_WORDS or "cerrad" in s or "resuelt" in s or "complet" in s or "done" in s:
        return "done"
    if s in _CURRENT_WORDS or "curso" in s or "progres" in s or "review" in s or "revis" in s:
        return "current"
    return "todo"


def _ticket_row(kind: str, t: dict) -> dict:
    """Fila plana (reopened/loose) — su único chip representa al ticket
    mismo, así Enter puede tratar toda fila igual (state.yaml)."""
    chip = {
        "id": t.get("id", ""), "summary": t.get("summary", ""),
        "status": t.get("status", ""), "_state": _chip_state(t.get("status", "")),
    }
    return {"_kind": kind, "label": t.get("summary", ""), "chips": [chip], "parent": None, "degraded": False}


def unique_parent_keys(tickets: list[dict]) -> list[str]:
    """Claves de parent únicas, en orden de primera aparición. Tickets sin
    parent se ignoran."""
    seen: set[str] = set()
    ordered: list[str] = []
    for t in tickets:
        parent = t.get("parent")
        key = parent.get("key") if parent else None
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def resolve_initial_board(tickets: list[dict], active_tid: str | None) -> str | None:
    """Tablero del ticket activo si existe entre `tickets`; si no, el primero
    alfabéticamente. `None` si no hay tickets. Se resuelve una sola vez por
    sesión — el llamador decide cuándo invocarla (nunca se persiste)."""
    if not tickets:
        return None
    if active_tid:
        for t in tickets:
            if t.get("id") == active_tid:
                return t.get("_board")
    boards = sorted({t.get("_board") for t in tickets if t.get("_board")})
    return boards[0] if boards else None


def build_board_rows(tickets: list[dict], siblings: dict[str, list[dict]], failed: set[str]) -> list[dict]:
    """Construye las filas del tablero activo en el orden reopened → cards →
    loose. `siblings` mapea parent_key -> subtasks (fetch_subtasks). `failed`
    marca parents cuyo fetch de subtasks falló — su card queda `degraded`
    (sin chips) en vez de tumbar todo el panel."""
    reopened_ids = {t["id"] for t in tickets if t.get("_bucket") == "reabiertos"}

    reopened_rows: list[dict] = []
    card_rows: list[dict] = []
    loose_rows: list[dict] = []
    seen_parents: set[str] = set()

    for t in tickets:
        if t.get("_bucket") == "reabiertos":
            reopened_rows.append(_ticket_row("reopened", t))
            continue

        parent = t.get("parent")
        parent_key = parent.get("key") if parent else None
        if not parent_key:
            loose_rows.append(_ticket_row("loose", t))
            continue

        if parent_key in seen_parents:
            continue
        seen_parents.add(parent_key)

        if parent_key in failed:
            card_rows.append({
                "_kind": "card", "label": parent.get("summary", ""),
                "chips": [], "parent": parent, "degraded": True,
            })
            continue

        raw_chips = siblings.get(parent_key, [])
        chips = [
            {
                "id": s.get("id", ""), "summary": s.get("summary", ""),
                "status": s.get("status", ""), "_state": _chip_state(s.get("status", "")),
            }
            for s in raw_chips
            if s.get("id") not in reopened_ids
        ]
        card_rows.append({
            "_kind": "card", "label": parent.get("summary", ""),
            "chips": chips, "parent": parent, "degraded": False,
        })

    return reopened_rows + card_rows + loose_rows


def move_focus(rows: list[dict], index: int, delta: int) -> int:
    """Índice de foco lineal, sujeto (clamped) a [0, len(rows)-1], sin
    wraparound."""
    if not rows:
        return 0
    return max(0, min(len(rows) - 1, index + delta))


def move_sub(rows: list[dict], index: int, sub: int, delta: int) -> int:
    """Índice de sub-foco (chip) dentro de la fila enfocada. No-op fuera de
    una card (reopened/loose/card degradada sin chips)."""
    if not rows or not (0 <= index < len(rows)):
        return sub
    row = rows[index]
    if row.get("_kind") != "card":
        return sub
    chip_count = len(row.get("chips", []))
    if chip_count == 0:
        return sub
    return max(0, min(chip_count - 1, sub + delta))


def target_ticket_id(rows: list[dict], index: int, sub: int) -> str | None:
    """Id del ticket que Enter debe activar: el chip sub-enfocado, o el
    parent de una card degradada (sin chips)."""
    if not rows or not (0 <= index < len(rows)):
        return None
    row = rows[index]
    chips = row.get("chips", [])
    if not chips:
        if row.get("_kind") == "card" and row.get("parent"):
            return row["parent"].get("key")
        return None
    sub = max(0, min(len(chips) - 1, sub))
    return chips[sub].get("id")


class TicketPanel(Widget):
    """Panel derecho — historias Jira asignadas al usuario, tablero activo
    con sus sub-tareas hermanas como chips. Focusable: dos índices reactivos
    (`_focus` fila, `_sub` chip) pintan un único `Text` — mismo patrón que
    `ProjectScreen._cursor`. Se refresca solo al montar, cada `r` manual, y
    cada 4 min en background."""

    can_focus = True

    class TicketSelected(Message):
        def __init__(self, ticket_id: str) -> None:
            self.ticket_id = ticket_id
            super().__init__()

    DEFAULT_CSS = f"""
    TicketPanel {{
        width: 1fr;
        height: 1fr;
        layout: vertical;
        border-left: solid {_BORDER};
    }}
    TicketPanel:focus {{
        border-left: solid {_ACCENT};
    }}
    TicketPanel:focus-within {{
        border-left: solid {_ACCENT};
    }}
    #tp-header {{
        height: 1;
        color: {_SECTION};
        text-style: bold;
        padding: 0 2;
        margin-top: 1;
    }}
    #tp-body {{
        height: 1fr;
        background: transparent;
        border: none;
        padding: 0 1;
    }}
    #tp-rows {{
        width: 100%;
        height: auto;
    }}
    #tp-divider {{
        color: {_BORDER};
        margin: 0 1;
        height: 1;
    }}
    #tp-desc {{
        height: 5;
        padding: 0 2;
        overflow-y: auto;
    }}
    #tp-foot {{
        height: 1;
        padding: 0 2;
        color: {_MUTED};
    }}
    """

    _AUTO_REFRESH_SECS = 240  # 4 min — mismo worker que "r", solo automático

    _focus: reactive[int] = reactive(0, init=False)
    _sub: reactive[int] = reactive(0, init=False)

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[dict] = []
        self._chip_memory: dict[str, int] = {}
        self._active_board: str | None = None
        self._board_resolved = False
        self._board_counts: dict[str, tuple[int, int]] = {}

    def compose(self) -> ComposeResult:
        yield Static("  TICKETS", id="tp-header", markup=False)
        with VerticalScroll(id="tp-body", can_focus=False):
            yield Static("", id="tp-rows", markup=False)
        yield Rule(id="tp-divider")
        yield Static("", id="tp-desc", markup=False)
        yield Static(
            f"  [[↵]] iniciar  ·  [[←/→]] chips  ·  [[b]] tablero  ·  [[r]] refrescar",
            id="tp-foot", markup=True,
        )

    def on_mount(self) -> None:
        self._fetch()
        self.set_interval(self._AUTO_REFRESH_SECS, self._fetch)

    @work(thread=True, exclusive=True)
    def _fetch(self) -> None:
        import os as _os
        from aicli.services.jira import fetch_my_issues, fetch_subtasks
        from aicli.services.tickets import load_tickets, read_active_ticket

        if not _os.getenv("JIRA_URL"):
            self.app.call_from_thread(self._set_desc, "JIRA_URL no configurada.")
            return
        try:
            grouped = fetch_my_issues()
        except Exception as e:
            self.app.call_from_thread(self._set_desc, f"Error Jira: {str(e)[:60]}")
            return

        # Los 3 buckets de fetch_my_issues son mutuamente excluyentes — cada
        # ticket cae en uno solo, no hace falta deduplicar entre ellos.
        flat: list[dict] = []
        for bucket in ("reabiertos", "alta_prioridad", "en_curso"):
            for item in grouped.get(bucket, []):
                item["_bucket"] = bucket
                flat.append(item)

        flat.sort(key=lambda x: _PRIO_ORDER.get(x.get("priority", ""), 99))

        local = load_tickets()
        active_data = read_active_ticket()
        active_tid = active_data["ticket_id"] if active_data else None
        for t in flat:
            t["_rounds"] = len(local.get(t["id"], {}).get("rondas", []))
            t["_active"] = (t["id"] == active_tid)
            t["_board"] = t["id"].split("-")[0] if "-" in t["id"] else t["id"]

        # El tablero activo se resuelve una sola vez por sesión (primer
        # fetch exitoso) — nunca se persiste ni se recalcula en refrescos
        # posteriores, a menos que el usuario lo cambie via `set_board`.
        if not self._board_resolved:
            self._active_board = resolve_initial_board(flat, active_tid)
            self._board_resolved = True

        board_counts: dict[str, tuple[int, int]] = {}
        for t in flat:
            b = t.get("_board", "")
            total, reopened = board_counts.get(b, (0, 0))
            total += 1
            if t.get("_bucket") == "reabiertos":
                reopened += 1
            board_counts[b] = (total, reopened)

        board_tickets = [t for t in flat if t.get("_board") == self._active_board]

        parent_keys = unique_parent_keys(board_tickets)
        siblings: dict[str, list[dict]] = {}
        failed: set[str] = set()
        for key in parent_keys:
            try:
                siblings[key] = fetch_subtasks(key)
            except Exception as e:
                logging.warning("TicketPanel._fetch subtasks %s — %s", key, e)
                failed.add(key)

        self.app.call_from_thread(self._populate, board_tickets, siblings, failed, board_counts)

    def _set_desc(self, msg) -> None:
        try:
            self.query_one("#tp-desc", Static).update(msg)
        except Exception:
            pass

    def _populate(
        self, tickets: list[dict], siblings: dict[str, list[dict]],
        failed: set[str], board_counts: dict[str, tuple[int, int]],
    ) -> None:
        self._board_counts = board_counts
        self._rows = build_board_rows(tickets, siblings, failed)
        self._focus = 0
        self._sub = self._chip_memory.get(self._row_key(0), 0) if self._rows else 0
        self._repaint()

    # ── Render ───────────────────────────────────────────────────────────────

    def watch__focus(self, value: int) -> None:
        self._repaint()

    def watch__sub(self, value: int) -> None:
        self._repaint()

    def _repaint(self) -> None:
        try:
            rows_widget = self.query_one("#tp-rows", Static)
        except Exception:
            return

        if not self._rows:
            board = self._active_board or "—"
            rows_widget.update(Text(f"  Sin tickets asignados en {board}", style=_MUTED))
            self._set_desc("")
            return

        txt = Text()
        for i, row in enumerate(self._rows):
            txt.append(self._row_text(row, i))
            txt.append("\n")
        rows_widget.update(txt)
        self._scroll_to_focus(self._focus)
        self._update_desc()

    def _row_text(self, row: dict, index: int) -> Text:
        focused_row = (index == self._focus)
        txt = Text(no_wrap=True, overflow="crop")

        if row.get("_kind") == "card":
            marker = "▶ " if focused_row else "  "
            txt.append(marker, style=f"bold {_ACCENT}" if focused_row else "")
            txt.append(row.get("label", ""), style="bold #F1F3F9" if focused_row else _SEC)

            if row.get("degraded"):
                parent = row.get("parent") or {}
                txt.append(f"  [{parent.get('key', '')}]", style=_ACCENT)
                txt.append("  (chips no disponibles)", style=_MUTED)
                return txt

            for ci, chip in enumerate(row.get("chips", [])):
                sub_focused = focused_row and ci == self._sub
                glyph, col = _CHIP_GLYPH.get(chip.get("_state"), ("·", _MUTED))
                style = f"reverse bold {col}" if sub_focused else col
                txt.append("  ")
                txt.append(f"{glyph} {chip.get('id', '')}", style=style)
            return txt

        # reopened / loose — la única chip representa al ticket mismo
        chip = (row.get("chips") or [{}])[0]
        marker = "▶ " if focused_row else "  "
        txt.append(marker, style=_OK if focused_row else "")
        tid = chip.get("id", "")
        summary = chip.get("summary", "")
        if len(summary) > 32:
            summary = summary[:31] + "…"
        txt.append(f"{tid:<13}", style=_ACCENT)
        txt.append(summary, style="bold #F1F3F9" if focused_row else _SEC)
        if row.get("_kind") == "reopened":
            txt.append("  ↻", style=_ERROR)
        return txt

    def _scroll_to_focus(self, line: int) -> None:
        try:
            container = self.query_one("#tp-body", VerticalScroll)
            container.scroll_to(y=line, animate=False)
        except Exception:
            pass

    def _update_desc(self) -> None:
        if not self._rows or not (0 <= self._focus < len(self._rows)):
            self._set_desc("")
            return
        row = self._rows[self._focus]
        chips = row.get("chips", [])
        if chips:
            sub = max(0, min(len(chips) - 1, self._sub))
            chip = chips[sub]
            txt = Text()
            txt.append(chip.get("id", "") + "  ", style=f"bold {_ACCENT}")
            txt.append(chip.get("summary", ""), style="bold #F1F3F9")
            if chip.get("status"):
                txt.append("\n")
                txt.append(chip["status"], style=_MUTED)
            self._set_desc(txt)
            return

        parent = row.get("parent") or {}
        txt = Text()
        txt.append(parent.get("key", "") + "  ", style=f"bold {_ACCENT}")
        txt.append(parent.get("summary", ""), style="bold #F1F3F9")
        self._set_desc(txt)

    # ── Board switcher support ──────────────────────────────────────────────

    def board_options(self) -> list[tuple[str, int, int]]:
        return sorted(
            (board, counts[0], counts[1])
            for board, counts in self._board_counts.items()
        )

    def active_board(self) -> str | None:
        return self._active_board

    def set_board(self, board: str) -> None:
        self._active_board = board
        self._rows = []
        self._focus = 0
        self._sub = 0
        self._repaint()
        self._fetch()

    # ── Keyboard navigation ─────────────────────────────────────────────────

    def _row_key(self, index: int) -> str:
        if not (0 <= index < len(self._rows)):
            return ""
        row = self._rows[index]
        parent = row.get("parent")
        if parent:
            return parent.get("key", "")
        return f"{row.get('_kind')}:{index}"

    def _remember_sub(self) -> None:
        key = self._row_key(self._focus)
        if key:
            self._chip_memory[key] = self._sub

    def focus_first(self) -> None:
        if self._rows:
            self._focus = 0
            self._sub = self._chip_memory.get(self._row_key(0), 0)

    def focus_last(self) -> None:
        if self._rows:
            self._focus = len(self._rows) - 1
            self._sub = self._chip_memory.get(self._row_key(self._focus), 0)

    def on_key(self, event) -> None:
        key = event.key
        if key == "r":
            self._fetch()
            event.stop()
        elif key == "up":
            self._focus = move_focus(self._rows, self._focus, -1)
            self._sub = self._chip_memory.get(self._row_key(self._focus), 0)
            event.stop()
        elif key == "down":
            self._focus = move_focus(self._rows, self._focus, 1)
            self._sub = self._chip_memory.get(self._row_key(self._focus), 0)
            event.stop()
        elif key == "left":
            self._sub = move_sub(self._rows, self._focus, self._sub, -1)
            self._remember_sub()
            event.stop()
        elif key == "right":
            self._sub = move_sub(self._rows, self._focus, self._sub, 1)
            self._remember_sub()
            event.stop()
        elif key == "enter":
            tid = target_ticket_id(self._rows, self._focus, self._sub)
            if tid:
                self.post_message(self.TicketSelected(tid))
            event.stop()
