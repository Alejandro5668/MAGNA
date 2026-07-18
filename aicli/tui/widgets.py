from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static, Rule, ListView, ListItem
from textual.message import Message
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


class TicketPanel(Widget):
    """Panel derecho — lista plana de tickets Jira asignados."""

    can_focus = False

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
    #tp-list {{
        height: 1fr;
        background: transparent;
        border: none;
        padding: 0 1;
    }}
    #tp-list > ListItem {{
        background: transparent;
        padding: 0 0;
        height: 1;
    }}
    #tp-list > ListItem.--highlight {{
        background: {_SELECT};
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

    def __init__(self) -> None:
        super().__init__()
        self._tickets: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Static("  TICKETS", id="tp-header", markup=False)
        yield ListView(id="tp-list")
        yield Rule(id="tp-divider")
        yield Static("", id="tp-desc", markup=False)
        yield Static(
            f"  [[↵]] iniciar tarea  ·  [[r]] refrescar",
            id="tp-foot", markup=True,
        )

    def on_mount(self) -> None:
        self._fetch()

    @work(thread=True, exclusive=True)
    def _fetch(self) -> None:
        import os as _os
        from aicli.services.jira import fetch_my_issues
        from aicli.services.tickets import load_tickets, read_active_ticket

        if not _os.getenv("JIRA_URL"):
            self.app.call_from_thread(self._set_desc, "JIRA_URL no configurada.")
            return
        try:
            grouped = fetch_my_issues()
        except Exception as e:
            self.app.call_from_thread(self._set_desc, f"Error Jira: {str(e)[:60]}")
            return

        seen: set[str] = set()
        flat: list[dict] = []
        for group_items in grouped.values():
            for item in group_items:
                if item["id"] not in seen:
                    seen.add(item["id"])
                    flat.append(item)

        flat.sort(key=lambda x: _PRIO_ORDER.get(x.get("priority", ""), 99))

        local = load_tickets()
        active_data = read_active_ticket()
        active_tid = active_data["ticket_id"] if active_data else None
        for t in flat:
            t["_rounds"] = len(local.get(t["id"], {}).get("rondas", []))
            t["_active"] = (t["id"] == active_tid)

        self.app.call_from_thread(self._populate, flat)

    def _set_desc(self, msg: str) -> None:
        try:
            self.query_one("#tp-desc", Static).update(msg)
        except Exception:
            pass

    def _populate(self, tickets: list[dict]) -> None:
        self._tickets = tickets
        lv = self.query_one("#tp-list", ListView)
        with self.app.batch_update():
            lv.clear()
            for t in tickets:
                lv.append(ListItem(Static(self._row(t)), id=f"tp-{t['id']}"))
        if tickets:
            self._update_desc(0)

    def _row(self, t: dict) -> Text:
        badge_ch, badge_col = _PRIO_BADGE.get(t.get("priority", ""), ("·", _MUTED))
        tid = t["id"]
        summary = t.get("summary", "")
        if len(summary) > 34:
            summary = summary[:33] + "…"
        txt = Text(no_wrap=True, overflow="crop")
        txt.append("▶ " if t.get("_active") else "  ", style=_OK if t.get("_active") else "")
        txt.append(badge_ch + " ", style=badge_col)
        txt.append(f"{tid:<13}", style=_ACCENT)
        txt.append(summary, style=_SEC)
        if t["_rounds"]:
            txt.append(f"  ⟳×{t['_rounds']}", style=_MUTED)
        return txt

    def _update_desc(self, index: int) -> None:
        if not self._tickets or index >= len(self._tickets):
            return
        t = self._tickets[index]
        txt = Text()
        txt.append(t["id"] + "  ", style=f"bold {_ACCENT}")
        txt.append(t.get("summary", ""), style="bold #F1F3F9")
        txt.append("\n")
        meta: list[str] = []
        if t.get("status"):
            meta.append(t["status"])
        if t.get("priority"):
            meta.append(t["priority"])
        if meta:
            txt.append("  ·  ".join(meta), style=_MUTED)
        self._set_desc(txt)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "tp-list" and event.item is not None:
            self._update_desc(event.list_view.index or 0)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "tp-list" and event.item is not None:
            idx = event.list_view.index or 0
            if idx < len(self._tickets):
                self.post_message(self.TicketSelected(self._tickets[idx]["id"]))

    def on_key(self, event) -> None:
        if event.key == "r":
            self._fetch()
            event.stop()
