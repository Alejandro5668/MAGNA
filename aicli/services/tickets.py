import json
import os
import time
from pathlib import Path
from datetime import datetime

_TICKETS_PATH = Path.home() / ".mycontext" / "tickets.json"
_SEGUNDOS_EXPIRACION = 7 * 86400


def _active_path() -> Path:
    # ponytail: PID per process so parallel MAGNA instances don't clobber each other
    return Path.home() / ".mycontext" / f"ticket_activo_{os.getpid()}.json"


def _load_raw() -> dict:
    if not _TICKETS_PATH.exists():
        return {}
    try:
        return json.loads(_TICKETS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(tickets: dict) -> None:
    tmp = _TICKETS_PATH.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(tickets, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_TICKETS_PATH)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


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


def get_ticket_branch(ticket_id: str) -> str | None:
    return _load_raw().get(ticket_id, {}).get("branch")


def save_ticket_branch(ticket_id: str, branch: str) -> None:
    tickets = _load_raw()
    if ticket_id not in tickets:
        tickets[ticket_id] = {"rondas": [], "ultima_actividad": 0}
    tickets[ticket_id]["branch"] = branch
    _save(tickets)


def save_active_ticket(ticket_id: str, motivo_reapertura: str) -> None:
    """Persiste el ticket y motivo de reapertura para que ctx sync los capture al cerrar."""
    p = _active_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"ticket_id": ticket_id, "motivo_reapertura": motivo_reapertura}, ensure_ascii=False),
        encoding="utf-8",
    )


def read_active_ticket() -> dict | None:
    path = _active_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def clear_active_ticket() -> None:
    path = _active_path()
    if path.exists():
        path.unlink()


def _session_ctx_file() -> Path:
    return Path.home() / ".mycontext" / f"session_ctx_{os.getpid()}.json"


def save_session_ctx_path(ctx_path: str) -> None:
    """Persiste la ruta del session_context creado en esta instancia (PID-scoped)."""
    f = _session_ctx_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(
        json.dumps({"ctx_path": ctx_path}, ensure_ascii=False),
        encoding="utf-8",
    )


def read_session_ctx_path() -> str | None:
    path = _session_ctx_file()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("ctx_path")
    except Exception:
        return None
