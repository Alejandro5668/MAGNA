import json
import os
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Callable

_SEGUNDOS_EXPIRACION = 7 * 86400
_MAX_HISTORY_ROUNDS = 5
_SESSION_STALE_SECONDS = 24 * 3600


def _base_dir() -> Path:
    """Directorio base de almacenamiento. Nunca cacheado — permite override
    en tests via la variable de entorno MYCONTEXT_HOME."""
    override = os.environ.get("MYCONTEXT_HOME")
    return Path(override) if override else Path.home() / ".mycontext"


def _legacy_tickets_path() -> Path:
    return _base_dir() / "tickets.json"


def _tickets_dir() -> Path:
    return _base_dir() / "tickets"


def _safe_id(ticket_id: str) -> str:
    """Sanea el ticket id para usarlo como nombre de archivo."""
    return re.sub(r"[^A-Z0-9_-]", "_", ticket_id.upper())


def _ticket_path(ticket_id: str) -> Path:
    return _tickets_dir() / f"{_safe_id(ticket_id)}.json"


def _qa_results_dir() -> Path:
    # Directorio propio: tickets/ lo recorre load_tickets() con glob("*.json")
    return _base_dir() / "qa_results"


def read_qa_result(ticket_id: str) -> dict | None:
    """Lee el resultado de verificación que dejó la sesión de Claude y lo consume
    (borra el archivo) para que un sync posterior no lea un resultado viejo.
    Devuelve None si no existe o si está corrupto."""
    path = _qa_results_dir() / f"{_safe_id(ticket_id)}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = None
    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
    return data if isinstance(data, dict) else None


def _new_ticket(ticket_id: str) -> dict:
    return {
        "descripcion": ticket_id,
        "rondas": [],
        "branch": None,
        "ultima_actividad": 0.0,
        "jira_cache": {"last_comment_id": None, "processed_attachments": {}},
    }


def _load_legacy_raw() -> dict:
    path = _legacy_tickets_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_ticket(ticket_id: str) -> dict | None:
    """Lee el archivo per-ticket. Si no existe, intenta migrar desde
    tickets.json (legacy) sin nunca tocar ese archivo."""
    path = _ticket_path(ticket_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    legacy = _load_legacy_raw()
    if ticket_id in legacy:
        data = _new_ticket(ticket_id)
        data.update(legacy[ticket_id])
        _write_ticket(ticket_id, data)
        return data
    return None


def _write_ticket(ticket_id: str, data: dict) -> None:
    _tickets_dir().mkdir(parents=True, exist_ok=True)
    path = _ticket_path(ticket_id)
    tmp = path.parent / f"{path.name}.{os.getpid()}.tmp"
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _mutate_ticket(ticket_id: str, mutate: Callable[[dict], None]) -> dict:
    """Re-lee el ticket, aplica la mutación y escribe atómicamente.
    El caller NUNCA debe pasar un dict obtenido antes de esta llamada —
    el re-read inmediato es lo que achica la ventana de pérdida de escrituras
    concurrentes al mismo ticket."""
    data = _read_ticket(ticket_id) or _new_ticket(ticket_id)
    mutate(data)
    data["ultima_actividad"] = time.time()
    _write_ticket(ticket_id, data)
    return data


def migrate_legacy_tickets() -> int:
    """Migración lazy y aditiva: crea el archivo per-ticket de cada entrada
    de tickets.json que todavía no lo tenga. Nunca borra ni reescribe
    tickets.json. Idempotente — tickets ya migrados no se vuelven a tocar."""
    legacy = _load_legacy_raw()
    if not legacy:
        return 0
    migrated = 0
    for ticket_id, entry in legacy.items():
        if _ticket_path(ticket_id).exists():
            continue
        data = _new_ticket(ticket_id)
        data.update(entry)
        _write_ticket(ticket_id, data)
        migrated += 1
    return migrated


def load_tickets() -> dict:
    """Migra tickets legacy pendientes, luego lee todos los archivos
    per-ticket, purgando (solo de la vista devuelta, nunca del disco) los
    que llevan más de 7 días sin actividad."""
    migrate_legacy_tickets()
    now = time.time()
    result: dict = {}
    for path in sorted(_tickets_dir().glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if now - data.get("ultima_actividad", 0) <= _SEGUNDOS_EXPIRACION:
            result[path.stem] = data
    return result


def save_round(
    ticket_id: str,
    description: str,
    archivos_tocados: list[str],
    mensaje_jira: str | None,
    motivo_reapertura: str | None = None,
    memoria: dict | None = None,
    qa_verified: bool | None = None,
) -> None:
    ronda = {
        "fecha": datetime.now().strftime("%Y-%m-%d"),
        "archivos_tocados": archivos_tocados,
        "mensaje_jira": mensaje_jira,
        "motivo_reapertura": motivo_reapertura,
        "memoria": memoria,
        "qa_verified": qa_verified,
    }

    def _mut(data: dict) -> None:
        if not data.get("descripcion") or data["descripcion"] == ticket_id:
            data["descripcion"] = description
        data.setdefault("rondas", [])
        data["rondas"].append(ronda)

    _mutate_ticket(ticket_id, _mut)


def format_history(ticket_id: str, tickets: dict) -> str | None:
    if ticket_id not in tickets:
        return None
    data = tickets[ticket_id]
    rondas = data.get("rondas", [])
    total = len(rondas)
    omitidas = max(0, total - _MAX_HISTORY_ROUNDS)
    shown = rondas[omitidas:]

    lines = [
        f"=== HISTORIAL DEL TICKET {ticket_id} ===",
        f"Descripcion: {data.get('descripcion', ticket_id)}",
        "",
    ]
    if omitidas:
        marcador = "ronda anterior omitida" if omitidas == 1 else "rondas anteriores omitidas"
        lines.append(f"({omitidas} {marcador})")
        lines.append("")

    for idx, ronda in enumerate(shown, start=omitidas + 1):
        lines.append(f"Ronda {idx} — {ronda['fecha']}")
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
    data = _read_ticket(ticket_id)
    return data.get("branch") if data else None


def save_ticket_branch(ticket_id: str, branch: str) -> None:
    def _mut(data: dict) -> None:
        data["branch"] = branch

    _mutate_ticket(ticket_id, _mut)


def get_jira_cache(ticket_id: str) -> dict:
    data = _read_ticket(ticket_id)
    default = {"last_comment_id": None, "processed_attachments": {}}
    if data is None:
        return default
    return data.get("jira_cache", default)


def save_comment_watermark(ticket_id: str, last_comment_id: str) -> None:
    def _mut(data: dict) -> None:
        data.setdefault("jira_cache", {"last_comment_id": None, "processed_attachments": {}})
        data["jira_cache"]["last_comment_id"] = last_comment_id

    _mutate_ticket(ticket_id, _mut)


def save_processed_attachments(ticket_id: str, entries: dict[str, dict]) -> None:
    """Merge — nunca reemplaza el dict de adjuntos ya procesados."""
    def _mut(data: dict) -> None:
        data.setdefault("jira_cache", {"last_comment_id": None, "processed_attachments": {}})
        data["jira_cache"].setdefault("processed_attachments", {})
        data["jira_cache"]["processed_attachments"].update(entries)

    _mutate_ticket(ticket_id, _mut)


def other_sessions_with_ticket(ticket_id: str) -> list[int]:
    """PIDs de otros procesos que tienen el mismo ticket activo, ignorando
    el propio PID y los marcadores de más de 24hs (abandonados) o corruptos."""
    own_pid = os.getpid()
    target = _safe_id(ticket_id)
    now = time.time()
    pattern = re.compile(r"^ticket_activo_(\d+)\.json$")
    pids: list[int] = []

    base = _base_dir()
    if not base.exists():
        return pids

    for path in base.glob("ticket_activo_*.json"):
        m = pattern.match(path.name)
        if not m:
            continue
        pid = int(m.group(1))
        if pid == own_pid:
            continue
        try:
            if now - path.stat().st_mtime > _SESSION_STALE_SECONDS:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        other_ticket = data.get("ticket_id")
        if other_ticket and _safe_id(str(other_ticket)) == target:
            pids.append(pid)
    return pids


def _active_path() -> Path:
    # ponytail: PID per process so parallel MAGNA instances don't clobber each other
    return _base_dir() / f"ticket_activo_{os.getpid()}.json"


def save_active_ticket(ticket_id: str, motivo_reapertura: str) -> None:
    """Persiste el ticket y motivo de reapertura para que ctx sync los capture al cerrar.
    Si motivo_reapertura viene vacío y el marcador ya apuntaba al mismo ticket,
    conserva el motivo guardado en vez de pisarlo (evita que _execute_task lo borre)."""
    path = _active_path()
    final_motivo = motivo_reapertura
    if not motivo_reapertura and path.exists():
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
            if prior.get("ticket_id") == ticket_id:
                final_motivo = prior.get("motivo_reapertura", "")
        except Exception:
            pass

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"ticket_id": ticket_id, "motivo_reapertura": final_motivo}, ensure_ascii=False),
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
    return _base_dir() / f"session_ctx_{os.getpid()}.json"


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
