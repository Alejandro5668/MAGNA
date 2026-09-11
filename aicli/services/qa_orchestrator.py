"""
Orquestador de QA automático — dispara un pipeline de verificación headless
tras cada `ctx sync`, comunicado únicamente por un blackboard de archivos en
`~/.mycontext/qa_results/<TICKET>/`.

Esta fase (Fase 2 del plan SDD) cubre la fundación: kill switch, layout del
blackboard, esquemas JSON y el helper `_git` con lista de comandos prohibidos.
El lanzamiento del proceso detached (Popen) que ejecuta el pipeline real se
agrega en la siguiente unidad de trabajo (Fase 3) — `trigger_qa()` todavía
NO lanza ningún subproceso; solo inicializa el blackboard y aplica el kill
switch.
"""
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

from aicli.services.tickets import _base_dir, _safe_id

# ── Esquemas (ver design.md — sección Interfaces) ────────────────────────────

STATUS_SCHEMA = "qa.status/1"
REPRO_SCHEMA = "qa.repro/1"
VERIFY_SCHEMA = "qa.verify/1"
REGRESSION_SCHEMA = "qa.regression/1"
VERDICT_SCHEMA = "qa.verdict/1"

# Artefactos de una corrida anterior que deben descartarse al superseder
# (nunca se mezclan corridas de distinto run_id).
_STAGE_ARTIFACTS = (
    "status.json", "repro.json", "verify.json", "regression.json",
    "verdict.json", "evidence.log",
)

# Comandos de git prohibidos para el helper `_git` — nunca se ejecuta código
# de red ni se cambia de branch/estado desde el pipeline automático.
_GIT_DENYLIST = {
    "push", "fetch", "pull", "remote", "reset", "checkout",
    "clean", "rebase", "merge", "cherry-pick",
}


# ── Blackboard: layout y escritura atómica ───────────────────────────────────

def _qa_results_base() -> Path:
    return _base_dir() / "qa_results"


def _run_dir(ticket_id: str) -> Path:
    """Directorio del blackboard para un ticket — nombre saneado vía
    tickets._safe_id() para que ids con espacios o metacaracteres de shell
    nunca terminen en un path o argv inseguro."""
    return _qa_results_base() / _safe_id(ticket_id)


def _write_json_atomic(path: Path, data: dict) -> None:
    """Mismo patrón tmp-then-replace() atómico que tickets._write_ticket."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f"{path.name}.{os.getpid()}.tmp"
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _reset_blackboard(run_dir: Path) -> None:
    """Descarta artefactos parciales de una corrida anterior para el mismo
    ticket (supersede cooperativo vía run_id nuevo) — nunca los mezcla con
    la corrida nueva."""
    run_dir.mkdir(parents=True, exist_ok=True)
    for name in _STAGE_ARTIFACTS:
        f = run_dir / name
        if f.exists():
            f.unlink()


def _new_status(run_id: str, ticket_id: str, project_path: str, branch: str | None) -> dict:
    now = time.time()
    return {
        "schema": STATUS_SCHEMA,
        "run_id": run_id,
        "ticket_id": ticket_id,
        "project_path": project_path,
        "branch": branch,
        "state": "pending",
        "stage": None,
        "attempt": 0,
        "pid": None,
        "started_at": now,
        "heartbeat": now,
        "events": [],
    }


# ── Punto de entrada ──────────────────────────────────────────────────────────

def trigger_qa(
    *,
    ticket_id: str,
    project_path: Path,
    files: list[str],
    branch: str | None = None,
) -> str | None:
    """Punto de entrada no-bloqueante del pipeline de QA automático.

    Kill switch: si la variable de entorno MAGNA_QA vale "off", desactiva el
    pipeline por completo y retorna None sin tocar el blackboard.

    Retorna el run_id (uuid4) de la corrida iniciada, o None si está
    deshabilitado. El lanzamiento real del proceso detached se agrega en la
    Fase 3 (unidad de trabajo siguiente) — esta función todavía no lanza
    ningún subproceso.
    """
    if os.environ.get("MAGNA_QA") == "off":
        return None

    run_id = str(uuid.uuid4())
    run_dir = _run_dir(ticket_id)
    _reset_blackboard(run_dir)

    status = _new_status(run_id, ticket_id, str(project_path), branch)
    _write_json_atomic(run_dir / "status.json", status)

    return run_id


# ── Parseo defensivo de JSON de agentes ──────────────────────────────────────

def _parse_agent_json(text: str) -> dict | None:
    """Parsea el JSON emitido por un stage de `claude -p`, tolerando fences
    de markdown y texto extra después del objeto JSON (mismo patrón que
    task.py::_detect_relevant_modules, ver commit a775146). Retorna None si
    el texto es irrecuperable — el llamador (qa_runner.py) es responsable de
    tratarlo como un error de stage."""
    stripped = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data, _ = json.JSONDecoder().raw_decode(stripped)
    except (ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


# ── Git seguro para el ciclo de corrección ───────────────────────────────────

def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Wrapper de git con lista de comandos prohibidos — nunca ejecuta
    push/fetch/pull/remote/reset/checkout/clean/rebase/merge/cherry-pick.
    Siempre list-argv, nunca shell=True. Siempre scoped al `cwd` recibido."""
    if args and args[0] in _GIT_DENYLIST:
        raise ValueError(f"comando git prohibido para el pipeline de QA: {args[0]}")
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, shell=False,
    )
