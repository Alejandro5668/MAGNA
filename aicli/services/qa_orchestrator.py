"""
Orquestador de QA automático — dispara un pipeline de verificación headless
tras cada `ctx sync`, comunicado únicamente por un blackboard de archivos en
`~/.mycontext/qa_results/<TICKET>/`.

Fase 2 (fundación): kill switch, layout del blackboard, esquemas JSON y el
helper `_git` con lista de comandos prohibidos.

Fase 3 (esta unidad): `trigger_qa()` ahora lanza el pipeline real como un
proceso OS detached que re-entra al mismo binario vía el subcomando oculto
`qa-run` (`aicli/commands/qa_cmd.py`). El lanzamiento nunca propaga una
excepción al llamador — una falla se registra en `status.json` como
`state:"error", reason:"launch_failed"` y `trigger_qa()` retorna `None`.
"""
import json
import os
import platform
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import aicli
from aicli.services.tickets import _base_dir, _safe_id

# ── Esquemas (ver design.md — sección Interfaces) ────────────────────────────

STATUS_SCHEMA = "qa.status/1"
REPRO_SCHEMA = "qa.repro/1"
VERIFY_SCHEMA = "qa.verify/1"
REGRESSION_SCHEMA = "qa.regression/1"
VERDICT_SCHEMA = "qa.verdict/1"
ENV_SCHEMA = "qa.env/1"
REVIEW_SCHEMA = "qa.review/1"

# Allowlist cerrada de categorías de seguridad que SÍ pueden mover un
# veredicto (design.md, decision 13) — la severidad que reporte el agente
# de review es decorativa, solo se escribe a evidence.log. Un vocabulario
# cerrado hace que el conjunto bloqueante sea revisable/diffable/testeable,
# y una categoría inventada o desconocida degrada a advisory en vez de a
# un veredicto aleatorio.
BLOCKING_SECURITY_CATEGORIES = frozenset({
    "sql_injection", "command_injection", "path_traversal", "unsafe_deserialization",
    "credential_exposure", "sensitive_data_exposure",
    "auth_bypass", "authorization_bypass", "xss", "ssrf",
})

# Artefactos de una corrida anterior que deben descartarse al superseder
# (nunca se mezclan corridas de distinto run_id).
_STAGE_ARTIFACTS = (
    "status.json", "repro.json", "verify.json", "regression.json",
    "review.json", "verdict.json", "evidence.log",
)

# Artefacto persistido POR TICKET — deliberadamente fuera de
# `_STAGE_ARTIFACTS` (design.md decision 8): `_reset_blackboard()` solo
# itera `_STAGE_ARTIFACTS`, así que este archivo sobrevive a todo
# `trigger_qa()`/`resume_qa()` por construcción, sin necesitar un caso
# especial en el loop de reset.
_ENV_CONTEXT_FILE = "env_context.json"
_PERSISTENT_ARTIFACTS = (_ENV_CONTEXT_FILE,)
assert not (set(_PERSISTENT_ARTIFACTS) & set(_STAGE_ARTIFACTS))

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


def _read_json_or_none(path: Path) -> dict | None:
    """Lee un JSON del blackboard tolerando que el archivo no exista todavía
    o esté siendo escrito (carrera con la escritura atómica del otro
    proceso) — nunca levanta, retorna None en cualquier falla de lectura."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


# ── Entorno confirmado por ticket (design decisions 8/9) ─────────────────────
#
# `_default_db_hint`/`_default_url_hint`/`_NO_CONFIGURADA` viven acá (no en
# qa_prompts.py) porque `env_preflight()` los necesita y qa_prompts.py YA
# importa de este módulo — importar en la otra dirección crearía un ciclo.
# qa_prompts.py importa estos tres símbolos de acá en vez de duplicarlos.

_NO_CONFIGURADA = "(no configurada)"


def _default_db_hint() -> str:
    return os.environ.get("MAGNA_QA_DEFAULT_DB") or _NO_CONFIGURADA


def _default_url_hint() -> str:
    return os.environ.get("MAGNA_QA_APP_URL") or _NO_CONFIGURADA


def _consume_answer(run_dir: Path) -> str | None:
    """Lee `run_dir/answer.json` y lo borra de inmediato — read-and-consume,
    para que un resume posterior no relacionado con esta pregunta nunca
    reuse una respuesta vieja. Vive acá (no en qa_prompts.py) porque
    `env_preflight()` también lo necesita; qa_prompts.py delega a esta
    misma función en vez de duplicarla."""
    path = run_dir / "answer.json"
    data = _read_json_or_none(path)
    if data is None:
        return None
    path.unlink(missing_ok=True)
    return data.get("value")


_ENV_ANSWER_MAX_LEN = 300
# Extracción estricta "db=<algo> url=<algo>" — cada mitad rechaza espacios,
# backticks, punto y coma y saltos de línea (threat matrix: subprocess/shell
# composition). Un input que no calza exactamente este patrón se rechaza
# entero, nunca se acepta parcialmente.
_ENV_ANSWER_RE = re.compile(r"^db=(?P<db>[^\s`;\r\n]+)\s+url=(?P<url>[^\s`;\r\n]+)$")


def _parse_env_answer(value: str) -> tuple[str | None, str | None]:
    """Parsea la respuesta de texto libre del usuario al pre-flight de
    entorno ("db=<nombre> url=<http://…>"). Nunca levanta: cualquier input
    inválido, peligroso o desmesuradamente largo retorna (None, None) — el
    llamador (`env_preflight`) lo trata como "hay que volver a preguntar",
    nunca como un valor parcialmente confiable."""
    if not value or len(value) > _ENV_ANSWER_MAX_LEN:
        return None, None
    if any(ch in value for ch in ("`", ";", "\n", "\r")):
        return None, None
    match = _ENV_ANSWER_RE.match(value.strip())
    if not match:
        return None, None
    return match.group("db"), match.group("url")


def read_env_context(run_dir: Path) -> dict | None:
    """Lee `env_context.json` — persiste fuera de `_STAGE_ARTIFACTS`, así
    que sobrevive a todo `_reset_blackboard()` (design.md, decision 8)."""
    return _read_json_or_none(run_dir / _ENV_CONTEXT_FILE)


def write_env_context(run_dir: Path, *, db: str, url: str, source: str) -> dict:
    """Escribe (atómico) la confirmación de entorno del ticket. `source` es
    `"user"` (el usuario tipeó db=/url= a mano) o `"default_confirmed"` (el
    usuario aceptó el default de `MAGNA_QA_DEFAULT_DB`/`MAGNA_QA_APP_URL`)."""
    env = {
        "schema": ENV_SCHEMA, "db": db, "url": url,
        "source": source, "confirmed_at": time.time(),
    }
    _write_json_atomic(run_dir / _ENV_CONTEXT_FILE, env)
    return env


def clear_env_context(run_dir: Path) -> None:
    """Borra `env_context.json` — usado cuando un repro `blocked` fuerza
    una re-confirmación de entorno (design decision 11). No-op si el
    archivo no existe, nunca levanta."""
    (run_dir / _ENV_CONTEXT_FILE).unlink(missing_ok=True)


_ENV_OTRO_LABEL = "Otro (escribir db y url a mano)"


def _env_select_question(ticket_id: str) -> dict:
    default_label = f"DB: {_default_db_hint()} · URL: {_default_url_hint()}"
    return {
        "kind": "select", "topic": "env",
        "prompt": f"QA {ticket_id} — ¿contra qué DB/URL verifico?",
        "options": [default_label, _ENV_OTRO_LABEL],
    }


def _env_text_question(ticket_id: str) -> dict:
    return {
        "kind": "text", "topic": "env", "options": None,
        "prompt": f"QA {ticket_id} — escribí el entorno así: db=<nombre> url=<http://…>",
    }


def env_preflight(run_dir: Path, ticket_id: str) -> tuple[dict | None, dict | None]:
    """Pre-flight puro Python (0 tokens) — Requirement: Pre-Flight DB/URL
    Confirmation. Retorna exactamente uno de `(env, None)` (contexto listo
    para usar) o `(None, question)` (el llamador debe pausar vía
    `_finalize_awaiting_input`). Invariante que resuelve a qué pregunta
    pertenece un `answer.json` pendiente: se consume acá SI Y SOLO SI
    `env_context.json` todavía no existe, porque el contexto se escribe
    antes del stage uno y nunca se resetea — ningún answer de
    verify/corrector puede estar pendiente mientras falta.

    Estados:
    - contexto ya confirmado ⇒ (env, None), `answer.json` NUNCA se toca.
    - sin contexto y sin respuesta pendiente ⇒ (None, pregunta select).
    - respuesta "Otro…" ⇒ (None, pregunta text), sin escribir contexto.
    - respuesta parseable ("db=… url=…") ⇒ escribe env_context.json,
      retorna (env, None).
    - respuesta no parseable (threat matrix) ⇒ (None, pregunta text de
      nuevo), sin escribir contexto — nunca acepta un valor parcial."""
    env = read_env_context(run_dir)
    if env is not None:
        return env, None

    answer = _consume_answer(run_dir)
    if answer is None:
        return None, _env_select_question(ticket_id)

    if answer == _ENV_OTRO_LABEL:
        return None, _env_text_question(ticket_id)

    default_db, default_url = _default_db_hint(), _default_url_hint()
    default_label = f"DB: {default_db} · URL: {default_url}"
    if answer == default_label and default_db != _NO_CONFIGURADA and default_url != _NO_CONFIGURADA:
        return write_env_context(run_dir, db=default_db, url=default_url, source="default_confirmed"), None

    db, url = _parse_env_answer(answer)
    if db is None or url is None:
        return None, _env_text_question(ticket_id)

    return write_env_context(run_dir, db=db, url=url, source="user"), None


# ── Lanzador detached: argv de re-entrada ────────────────────────────────────

def _main_py() -> Path:
    return Path(aicli.__file__).resolve().parents[1] / "main.py"


def _qa_run_argv(ticket_id: str, project_path: Path, run_id: str) -> list[str]:
    """Construye el argv de re-entrada al mismo binario vía el subcomando
    oculto `qa-run`. En modo frozen (PyInstaller) `sys.executable` ya ES el
    ejecutable de MAGNA; en modo dev hay que apuntar explícitamente a
    `main.py`, porque `python -m ...` no existe para el binario empaquetado.

    Las opciones van ANTES del argumento posicional `ticket_id` a propósito:
    Click/Typer trata a `qa_cmd.app` como un grupo (por el
    `@app.callback(invoke_without_command=True)`, igual que `task.py` y
    `archive.py`), y un grupo intenta despachar el primer token no-opción
    como subcomando en cuanto lo ve — poner el positional al final es la
    única forma verificada de que el parseo no lo confunda con un
    subcomando inexistente."""
    if getattr(sys, "frozen", False):
        prefix = [sys.executable, "qa-run"]
    else:
        prefix = [sys.executable, str(_main_py()), "qa-run"]
    return [*prefix, "--project-path", str(project_path), "--run-id", run_id, ticket_id]


def _launch_qa_run(
    run_dir: Path, status: dict, status_path: Path,
    ticket_id: str, project_path: Path, run_id: str,
) -> str | None:
    """Lanza el proceso OS detached de re-entrada a `qa-run` — factorizado de
    `trigger_qa()` para que `resume_qa()` (reanudación tras `needs_input`)
    reuse exactamente la misma mecánica de lanzamiento, en vez de duplicarla.
    Nunca propaga una excepción: una falla se refleja en `status.json` como
    `state:"error", reason:"launch_failed"` y retorna None."""
    argv = _qa_run_argv(ticket_id, project_path, run_id)
    try:
        with open(run_dir / "run.log", "a", encoding="utf-8") as log:
            proc = subprocess.Popen(
                argv,
                cwd=str(project_path),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                close_fds=True,
                **_popen_kwargs(),
            )
    except Exception:
        status["state"] = "error"
        status["reason"] = "launch_failed"
        _write_json_atomic(status_path, status)
        return None

    status["pid"] = proc.pid
    _write_json_atomic(status_path, status)
    return run_id


def _popen_kwargs() -> dict:
    """kwargs de detach validados por el spike S3: en Windows,
    DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW; en otras
    plataformas, start_new_session=True (setsid)."""
    if platform.system() == "Windows":
        return {
            "creationflags": (
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            )
        }
    return {"start_new_session": True}


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

    Lanza el pipeline como un proceso OS detached que re-entra al mismo
    binario (`qa-run <TICKET> --project-path <p> --run-id <id>`), con
    stdin/stdout/stderr nunca heredados de la terminal — sobrevive al cierre
    de la terminal o del TUI que lo disparó (spike S3).

    Retorna el run_id (uuid4) de la corrida iniciada, o None si está
    deshabilitado o si el lanzamiento falló. Una falla de lanzamiento NUNCA
    propaga una excepción al llamador: se registra en status.json como
    state:"error", reason:"launch_failed".
    """
    if os.environ.get("MAGNA_QA") == "off":
        return None

    run_id = str(uuid.uuid4())
    run_dir = _run_dir(ticket_id)
    _reset_blackboard(run_dir)

    status = _new_status(run_id, ticket_id, str(project_path), branch)
    status_path = run_dir / "status.json"
    _write_json_atomic(status_path, status)

    return _launch_qa_run(run_dir, status, status_path, ticket_id, project_path, run_id)


# ── needs_input: respuesta del usuario + reanudación ─────────────────────────

def write_qa_answer(ticket_id: str, value: str) -> None:
    """Escribe `run_dir/answer.json` con la respuesta del usuario a un
    `needs_input` pendiente. El próximo `build_verify_prompt`/
    `build_corrector_prompt` la consume (lee y borra) en el resume
    subsiguiente — llamar ANTES de `resume_qa()`."""
    run_dir = _run_dir(ticket_id)
    _write_json_atomic(run_dir / "answer.json", {"value": value})


def resume_qa(ticket_id: str, project_path: Path) -> None:
    """Reanuda una corrida en pausa (`status.state == "awaiting_input"`) tras
    que el usuario respondió (se asume que `write_qa_answer()` ya escribió
    `answer.json` antes de esta llamada). No-op si no hay ninguna corrida, o
    si la corrida existente no está esperando una respuesta — nunca arranca
    una corrida nueva ni levanta una excepción.

    Reusa el mismo `run_id` de la corrida pausada (así el supersede
    cooperativo de `qa_cmd.qa_run()` sigue aceptando este proceso), resetea
    los artefactos de stage de la corrida anterior igual que un `trigger_qa()`
    nuevo (pero preserva `answer.json`, ya escrito por el llamador) y agrega
    —nunca reemplaza— un evento nuevo al historial `events[]` existente.

    Deliberadamente NO hace resume parcial/checkpointed: repro → verify →
    regression se vuelven a correr enteros, ahora con la respuesta disponible
    para que el stage que la necesitaba no vuelva a preguntar (ver brief —
    over-engineering un checkpoint no vale la pena para este caso, poco
    frecuente, con stages rápidos)."""
    run_dir = _run_dir(ticket_id)
    status_path = run_dir / "status.json"
    status = _read_json_or_none(status_path)
    if status is None or status.get("state") != "awaiting_input":
        return

    run_id = status["run_id"]
    events = status.get("events") or []
    seq = (events[-1]["seq"] + 1) if events else 1
    events = [*events, {
        "seq": seq, "ts": time.time(), "kind": "resume",
        "msg": "Reanudado tras respuesta del usuario",
    }]

    _reset_blackboard(run_dir)

    status = {
        **status,
        "state": "pending",
        "stage": None,
        "pid": None,
        "heartbeat": time.time(),
        "events": events,
    }
    status.pop("question", None)
    _write_json_atomic(status_path, status)

    _launch_qa_run(run_dir, status, status_path, ticket_id, project_path, run_id)


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


# ── Lectura de estado + badge para la superficie del TUI (Fase 7) ───────────
#
# Colores duplicados literalmente de la paleta MAGNA (aicli/tui/widgets.py:
# _ACCENT/_OK/_WARN/_ERROR) en vez de importados: este módulo es un service,
# nunca debe depender de aicli.tui (evita import circular — widgets.py SÍ
# importa qa_orchestrator, nunca al revés).
_BADGE_ACCENT = "#FFB703"
_BADGE_OK = "#4ADE80"
_BADGE_WARN = "#FBBF24"
_BADGE_ERROR = "#F87171"

# heartbeat > este umbral en un estado no-terminal ⇒ la corrida se considera
# stale (proceso probablemente murió sin escribir el estado final).
STALE_THRESHOLD_SECONDS = 600

_TERMINAL_STATUS_STATES = {"done", "error"}

# Estados que nunca deben marcarse stale: terminales (ya no laten) más
# awaiting_input (pausado esperando al usuario indefinidamente — eso es
# comportamiento esperado, no un signo de que el proceso murió).
_NEVER_STALE_STATES = _TERMINAL_STATUS_STATES | {"awaiting_input"}


def qa_evidence_log_path(ticket_id: str) -> Path:
    """Ruta pública al `evidence.log` del ticket — para que el TUI no tenga
    que alcanzar el helper privado `_run_dir` desde otro módulo (Requirement:
    Evidence Viewable on Demand)."""
    return _run_dir(ticket_id) / "evidence.log"


def read_qa_status(ticket_id: str) -> dict | None:
    """Lee status.json del blackboard del ticket, aplicando staleness: un
    estado no-terminal cuyo heartbeat lleva más de STALE_THRESHOLD_SECONDS sin
    refrescarse se marca `stale: True` (el proceso probablemente murió sin
    escribir un estado final). Retorna None si nunca hubo una corrida."""
    status = _read_json_or_none(_run_dir(ticket_id) / "status.json")
    if status is None:
        return None
    if status.get("state") not in _NEVER_STALE_STATES:
        heartbeat = status.get("heartbeat") or 0
        if (time.time() - heartbeat) > STALE_THRESHOLD_SECONDS:
            status = {**status, "stale": True}
    return status


def read_qa_badge(ticket_id: str) -> dict | None:
    """Traduce el estado del blackboard a un badge `{"ch","col","state"}` para
    `TicketPanel._row()` — vocabulario exacto de qa-status-surface/spec.md:
    none (retorna None) / in-progress / pass / fail / doubtful / manual-review
    / error. Símbolo Y color siempre juntos — nunca color solo."""
    status = read_qa_status(ticket_id)
    if status is None:
        return None
    if status.get("stale") or status.get("state") == "error":
        return {"ch": "⚠", "col": _BADGE_ERROR, "state": "error"}
    if status.get("state") == "awaiting_input":
        # Distinto de "in-progress": el pipeline no está avanzando solo,
        # está pausado esperando que el usuario responda una pregunta.
        return {"ch": "⏸", "col": f"bold {_BADGE_ACCENT}", "state": "awaiting-input"}
    if status.get("state") != "done":
        return {"ch": "◔", "col": _BADGE_ACCENT, "state": "in-progress"}

    verdict = _read_json_or_none(_run_dir(ticket_id) / "verdict.json")
    verdict_name = (verdict or {}).get("verdict")
    if verdict_name == "passed":
        return {"ch": "✓", "col": _BADGE_OK, "state": "passed"}
    if verdict_name == "manual_review":
        return {"ch": "!", "col": f"bold {_BADGE_WARN}", "state": "manual-review"}
    if verdict_name == "dudoso":
        return {"ch": "?", "col": _BADGE_WARN, "state": "doubtful"}
    if verdict_name == "failed":
        return {"ch": "✗", "col": _BADGE_ERROR, "state": "failed"}
    # state="done" pero verdict.json ilegible/ausente — no debería pasar en
    # operación normal, pero nunca debe mostrarse como "passed" por defecto.
    return {"ch": "⚠", "col": _BADGE_ERROR, "state": "error"}


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
