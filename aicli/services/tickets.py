import json
import time
from pathlib import Path
from datetime import datetime

_TICKETS_PATH = Path.home() / ".mycontext" / "tickets.json"
_ACTIVO_PATH = Path.home() / ".mycontext" / "ticket_activo.json"
_SEGUNDOS_EXPIRACION = 7 * 86400


def _load_raw() -> dict:
    if not _TICKETS_PATH.exists():
        return {}
    try:
        return json.loads(_TICKETS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(tickets: dict) -> None:
    _TICKETS_PATH.write_text(json.dumps(tickets, ensure_ascii=False, indent=2), encoding="utf-8")


def load_tickets() -> dict:
    """Carga tickets activos, purgando los de más de 7 días sin actividad."""
    raw = _load_raw()
    now = time.time()
    activos = {
        tid: data
        for tid, data in raw.items()
        if now - data.get("ultima_actividad", 0) <= _SEGUNDOS_EXPIRACION
    }
    if len(activos) != len(raw):
        _save(activos)
    return activos


def save_round(
    ticket_id: str,
    description: str,
    archivos_tocados: list[str],
    mensaje_jira: str | None,
    motivo_reapertura: str | None = None,
    memoria: dict | None = None,
) -> None:
    tickets = _load_raw()
    now = time.time()

    ronda = {
        "fecha": datetime.now().strftime("%Y-%m-%d"),
        "archivos_tocados": archivos_tocados,
        "mensaje_jira": mensaje_jira,
        "motivo_reapertura": motivo_reapertura,
        "memoria": memoria,
    }

    if ticket_id not in tickets:
        tickets[ticket_id] = {"descripcion": description, "rondas": [], "ultima_actividad": now}
    else:
        tickets[ticket_id]["ultima_actividad"] = now

    tickets[ticket_id]["rondas"].append(ronda)
    _save(tickets)


def format_history(ticket_id: str, tickets: dict) -> str | None:
    if ticket_id not in tickets:
        return None
    data = tickets[ticket_id]
    lines = [
        f"=== HISTORIAL DEL TICKET {ticket_id} ===",
        f"Descripcion: {data['descripcion']}",
        "",
    ]
    for i, ronda in enumerate(data["rondas"], 1):
        lines.append(f"Ronda {i} — {ronda['fecha']}")
        if ronda.get("motivo_reapertura"):
            lines.append(f"Motivo de reapertura: {ronda['motivo_reapertura']}")
        if ronda.get("archivos_tocados"):
            lines.append(f"Archivos tocados: {', '.join(ronda['archivos_tocados'])}")
        mem = ronda.get("memoria")
        if mem:
            if mem.get("investigado"):
                lines.append(f"Investigado: {mem['investigado']}")
            if mem.get("hecho"):
                lines.append(f"Hecho: {mem['hecho']}")
            if mem.get("tener_en_cuenta"):
                lines.append(f"Tener en cuenta: {mem['tener_en_cuenta']}")
        elif ronda.get("mensaje_jira"):
            lines.append(f"Solucion aplicada:\n{ronda['mensaje_jira']}")
        lines.append("")
    lines.append("=== FIN HISTORIAL ===")
    return "\n".join(lines)


def save_active_ticket(ticket_id: str, motivo_reapertura: str) -> None:
    """Persiste el ticket y motivo de reapertura para que ctx sync los capture al cerrar."""
    _ACTIVO_PATH.write_text(
        json.dumps({"ticket_id": ticket_id, "motivo_reapertura": motivo_reapertura}, ensure_ascii=False),
        encoding="utf-8",
    )


def read_active_ticket() -> dict | None:
    if not _ACTIVO_PATH.exists():
        return None
    try:
        return json.loads(_ACTIVO_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def clear_active_ticket() -> None:
    if _ACTIVO_PATH.exists():
        _ACTIVO_PATH.unlink()
