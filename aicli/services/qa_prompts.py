"""
Prompts (contratos de rol) para los tres stages headless del pipeline de QA
automático — repro, verify, corrector — más el helper de invocación headless
compartido por los tres (Fase 4 del plan SDD).

Cada prompt se escribe a un archivo bajo `run_dir/prompts/<stage>.md` — nunca
se pasa el contenido completo por argv (mismo patrón que
`caller.launch_claude`, que evita el límite de longitud de argv en Windows
escribiendo a `session_context_*.md` y pasando solo un mensaje corto que
apunta al archivo).

Spike S2 (ver design.md / apply-progress de la unidad anterior) confirmó que
la llamada posicional bare `-p "<mensaje>"` alcanza para Read headless, sin
flags de modo de permisos. Un spike adicional de ESTA unidad confirmó que
Edit/Write headless también funciona sin flags extra (ni hang, ni prompt de
confirmación) — ver Deviations en apply-progress. `invoke_stage()` se
mantiene deliberadamente simple: bare `-p`, sin `--output-format`.
"""
import os
import platform
import subprocess
import threading
from pathlib import Path

from aicli.services.caller import _find_claude_windows
from aicli.services.qa_orchestrator import (
    _consume_answer,
    _default_db_hint,
    _default_url_hint,
)

STAGE_TIMEOUT_SECONDS = 600

# Variables que NUNCA deben llegarle al subproceso `claude -p`: si están
# seteadas (p. ej. un .env de proyecto con ANTHROPIC_API_KEY para el indexer
# de MAGNA, que sí la necesita para su propio uso de la SDK), el CLI de
# Claude Code las prioriza sobre la sesión de suscripción ya logueada y
# factura contra la API en vez de usar la suscripción — exactamente lo que
# este pipeline de QA existe para NO hacer.
_STRIP_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def _subprocess_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in _STRIP_ENV_VARS}


_DB_ACCESS_RULE = """
## Regla de acceso a base de datos (dos niveles, sin excepción)

- Contra CUALQUIER base de datos de PRODUCCIÓN: acceso de SOLO LECTURA,
  siempre, sin excepción — nunca hagas una escritura de producción (ni DB ni
  API).
- Contra CUALQUIER base de datos LOCAL o de TEST: libertad total de lectura Y
  escritura — podés crear tus propios fixtures de test ahí.
""".strip()


def _default_config_block() -> str:
    return f"""## Configuración por defecto

- Base de datos de pruebas por defecto (MAGNA_QA_DEFAULT_DB): {_default_db_hint()}
- URL de entorno de pruebas (MAGNA_QA_APP_URL): {_default_url_hint()}

Si hay un valor configurado arriba, usalo y no preguntes. Si no hay valor
configurado, o si el contexto de este ticket específico te hace dudar de que
el default aplique (por ejemplo, parece necesitar datos de un cliente
puntual), inspeccioná la configuración propia del proyecto (.env,
docker-compose, etc. — ya tenés acceso de lectura/shell) para encontrar
candidatos de DB/URL locales. Si sigue siendo genuinamente ambiguo, o parece
requerir un backup de cliente no disponible, NO ASUMAS: completá
"needs_input" en la salida en vez de adivinar (kind="select" con los
candidatos encontrados, o kind="text" preguntando directamente, por ejemplo
qué backup de cliente usar).""".strip()


def _answer_block(run_dir: Path) -> str:
    answer = _consume_answer(run_dir)
    if answer is None:
        return ""
    return f"\nEl usuario ya respondió esto: `{answer}` — usalo, no vuelvas a preguntar lo mismo.\n"

SECURITY_CHECKLIST = """
## Checklist de seguridad (aplica SIEMPRE, incluso sin skill/MCP disponible)

- Nunca ejecutes `git push`, `git fetch`, `git pull`, `git reset --hard`, `git checkout` a otra rama, ni ningún comando que toque un remoto.
- Nunca modifiques archivos fuera de la lista de "archivos permitidos" provista abajo.
- Nunca uses `shell=True` ni compongas comandos de shell con datos externos.
- Nunca commitees vos mismo — el pipeline se encarga del commit después de tu edición.
- Si detectás que la corrección requeriría tocar un archivo fuera del alcance permitido, DETENÉ el intento y reportalo en tu salida en vez de forzarlo.
- Si el skill `security-review` o herramientas de CodeGraph están disponibles en esta sesión, usalas para revisar tu propio diff antes de finalizar.
""".strip()


def _write_prompt(run_dir: Path, stage: str, content: str) -> Path:
    prompts_dir = run_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    path = prompts_dir / f"{stage}.md"
    path.write_text(content, encoding="utf-8")
    return path


_REPRO_ISOLATION_CLAUSE = """
## Aislamiento del diff de la corrección (obligatorio)

No busques ni inspecciones el diff de la corrección, el mensaje de commit, ni
el historial reciente del repositorio. Tenés PROHIBIDO ejecutar `git log`,
`git diff`, `git show` o `git blame`, o leer commits recientes de cualquier
otra forma. Actuá como si no supieras si el proyecto ya fue modificado para
atender este reporte.
""".strip()


def _confirmed_env_block(env: dict) -> str:
    return f"""## Entorno confirmado para este ticket

- Base de datos: {env.get("db")}
- URL: {env.get("url")}

Usá este entorno — ya fue confirmado por el usuario, no preguntes por otro.""".strip()


def build_repro_prompt(run_dir: Path, ticket_id: str, ticket_history: str, env: dict) -> Path:
    """Prompt de repro — Requirement: Repro Stage Isolation. SOLO recibe el
    reporte/historial original del ticket más el entorno YA confirmado
    (`env_preflight`, design decision 9); NUNCA recibe (ni tiene parámetro
    capaz de cargar) el diff de la corrección, el mensaje de commit, ni la
    lista de archivos tocados — deliberadamente no gana `_answer_block()`
    (podría nombrar el fix) ni `_default_config_block()` (invita a
    arqueología del repo). El aislamiento es estructural (firma sin
    parámetro de diff/files/commit) más una cláusula anti-lookup explícita:
    un scan de texto sería derrotado por la cláusula misma, que necesita
    nombrar `diff`/`commit` para prohibirlos (design.md, decision 10)."""
    content = f"""# Rol: QA Repro Agent

Tu única tarea es intentar reproducir el bug reportado para el ticket
{ticket_id}, usando EXCLUSIVAMENTE el reporte/historial de abajo. No busques
ni asumas ningún cambio de código relacionado — actuá como si no supieras
si el proyecto ya fue modificado para atender este reporte.

{_DB_ACCESS_RULE}

{_confirmed_env_block(env)}

{_REPRO_ISOLATION_CLAUSE}

## Reporte / historial del ticket

{ticket_history or "(sin historial adicional)"}

## Qué hacer

1. Intentá reproducir el bug siguiendo los pasos reportados, usando el
   entorno confirmado arriba.
2. Registrá los pasos que seguiste, el resultado esperado y el resultado real.
3. Si la base de datos o el navegador no responden o te bloquean el intento
   a mitad de camino, NO inventes un resultado: marcá "status": "blocked" y
   contá qué pasó en "blocked_reason".

## Formato de salida — ÚNICAMENTE este JSON, sin texto adicional

{{
  "schema": "qa.repro/1",
  "status": "reproduced" | "not_reproduced" | "blocked",
  "steps": ["paso 1", "paso 2"],
  "expected": "...",
  "actual": "...",
  "evidence": [],
  "notes": "...",
  "blocked_reason": null
}}
"""
    return _write_prompt(run_dir, "repro", content)


def build_verify_prompt(run_dir: Path, ticket_id: str, ticket_history: str) -> Path:
    """Prompt de verify — Requirement: Verify Stage Contract. Navegador real
    + regla de acceso a base de datos de dos niveles explícita (nunca solo
    "acceso de solo lectura" a secas — eso era ambiguo, ver brief). Si el
    default de DB/URL configurado no aplica o no existe, el agente debe usar
    `needs_input` en vez de adivinar."""
    content = f"""# Rol: QA Verify Agent

Tu tarea es re-intentar, con un navegador real, los mismos pasos del bug
reportado para el ticket {ticket_id}.

{_DB_ACCESS_RULE}

{_default_config_block()}
{_answer_block(run_dir)}
## Reporte / historial del ticket

{ticket_history or "(sin historial adicional)"}

## Qué hacer

1. Repetí los pasos de reproducción en el navegador.
2. Confirmá si el comportamiento reportado ya NO ocurre (pass) o sigue
   ocurriendo (fail).

## Formato de salida — ÚNICAMENTE este JSON, sin texto adicional

{{
  "schema": "qa.verify/1",
  "status": "pass" | "fail",
  "checks": [{{"name": "...", "result": "pass|fail", "detail": "..."}}],
  "evidence": [],
  "db_reads": [],
  "error": null,
  "needs_input": {{"kind": "text" | "select", "prompt": "...", "options": ["...", "..."] | null}} | null
}}
"""
    return _write_prompt(run_dir, "verify", content)


def build_corrector_prompt(
    run_dir: Path,
    ticket_id: str,
    attempt: int,
    max_attempts: int,
    archivos_tocados: list[str],
    git_diff: str,
    failure_reason: str,
) -> Path:
    """Prompt del corrector — Requirement: File Scoping for Corrections.
    SIEMPRE inlinea SECURITY_CHECKLIST y SIEMPRE limita el contexto/edición a
    `archivos_tocados`. Asume que no hay skill `security-review` ni MCP
    disponibles — ambos son, a lo sumo, oportunistas (design decision 5)."""
    files_list = "\n".join(f"- {f}" for f in archivos_tocados) or "(ninguno registrado)"
    content = f"""# Rol: QA Corrector Agent — intento {attempt}/{max_attempts}

El ticket {ticket_id} falló su verificación. Tu tarea es corregir el
problema editando ÚNICAMENTE los archivos permitidos listados abajo. NO
edites ningún otro archivo.

{_DB_ACCESS_RULE}

{_default_config_block()}
{_answer_block(run_dir)}
## Motivo de la falla

{failure_reason}

## Archivos permitidos para editar (y ningún otro)

{files_list}

## Diff de la corrección original (contexto — no lo repitas, no lo commitees)

```diff
{git_diff or "(sin diff disponible)"}
```

{SECURITY_CHECKLIST}

## Qué hacer

1. Diagnosticá por qué la verificación falló.
2. Editá SOLO los archivos permitidos listados arriba para corregirlo.
3. No hagas `git commit` vos — el pipeline se encarga de eso después.

## Formato de salida — ÚNICAMENTE este JSON, sin texto adicional

{{
  "schema": "qa.correction/1",
  "status": "applied" | "error",
  "motivo": "resumen corto del cambio, para el mensaje de commit",
  "error": null,
  "needs_input": {{"kind": "text" | "select", "prompt": "...", "options": ["...", "..."] | null}} | null
}}
"""
    return _write_prompt(run_dir, f"correction_{attempt}", content)


REVIEW_CONDUCT_RULES = """
## Reglas de conducta (SIEMPRE, sin excepción)

- Esto es una revisión de SOLO LECTURA: nunca edites archivos, nunca hagas
  `git add`/`git commit`, y nunca corras migraciones ni escrituras de base
  de datos.
- Limitate a inspeccionar el diff y los archivos tocados provistos abajo —
  nunca el repositorio completo.
- Nunca ejecutes `git push`, `git fetch`, `git pull`, `git reset`,
  `git checkout` a otra rama, ni ningún comando que toque un remoto.
""".strip()


def build_review_prompt(run_dir: Path, ticket_id: str, archivos_tocados: list[str], git_diff: str) -> Path:
    """Prompt de review — Requirement: Review Stage Contract. Recibe
    ÚNICAMENTE el diff de la corrección y la lista de archivos tocados
    (nunca el repo completo — threat matrix: diff scope blowout, resuelto
    en la capa de arriba por `_review_diff`). Pide dos secciones
    estructuralmente separadas — `security` y `quality` — porque el
    agregador solo puede juzgar `security` contra un allowlist cerrado
    (design.md, decision 13); `quality` es siempre asesoramiento."""
    files_list = "\n".join(f"- {f}" for f in archivos_tocados) or "(ninguno registrado)"
    content = f"""# Rol: QA Review Agent

Tu tarea es revisar el diff de la corrección aplicada para el ticket
{ticket_id}. Revisá ÚNICAMENTE lo que está en el diff de abajo, nunca el
repositorio completo.

{REVIEW_CONDUCT_RULES}

## Archivos tocados

{files_list}

## Diff a revisar

```diff
{git_diff or "(sin diff disponible)"}
```

## Qué hacer

1. Buscá hallazgos de seguridad. Nombrá la categoría con la mayor precisión
   posible (por ejemplo: sql_injection, command_injection, path_traversal,
   unsafe_deserialization, credential_exposure, sensitive_data_exposure,
   auth_bypass, authorization_bypass, xss, ssrf, u otra si no calza en
   ninguna de estas). La severidad que reportes es solo informativa — no
   decide nada por su cuenta.
2. Buscá hallazgos de calidad (duplicación, código muerto, convención) por
   separado — nunca afectan el veredicto final.

## Formato de salida — ÚNICAMENTE este JSON, sin texto adicional

{{
  "schema": "qa.review/1",
  "status": "ok",
  "security": {{"findings": [{{"category": "...", "file": "...", "line": 0,
                              "detail": "...", "severity": "..."}}]}},
  "quality": {{"findings": [{{"kind": "...", "file": "...", "line": 0,
                             "detail": "...", "existing": "..."}}]}},
  "error": null
}}
"""
    return _write_prompt(run_dir, "review", content)


def invoke_stage(
    prompt_path: Path,
    cwd: Path,
    *,
    run_dir: Path,
    stage: str,
    timeout: int = STAGE_TIMEOUT_SECONDS,
) -> str:
    """Invoca `claude -p` headless apuntando al archivo de prompt (nunca el
    contenido completo por argv). Retorna stdout crudo; el llamador es
    responsable de parsearlo vía `qa_orchestrator._parse_agent_json()`.
    Nunca `shell=True`; siempre list-argv.

    Streaming en vivo: la salida se lee línea por línea a medida que llega y
    se vuelca a `run_dir/live/<stage>.log` (truncado al arrancar — un intento
    nuevo del stage nunca debe empezar mostrando el log en vivo de un intento
    viejo), además de acumularse en memoria para el retorno de siempre. Eso
    es lo que `QaDetailScreen` tailea mientras el stage está corriendo.

    stderr va a DEVNULL a propósito, no a un segundo pipe: ya se descartaba
    antes (solo `.stdout` se usaba) y leer dos pipes en simultáneo sin
    deadlockear necesita threads/selectors que esto no necesita para lo que
    de verdad se usa.

    El proceso `qa-run` que llama a esto corre detached y sin consola propia
    (`_popen_kwargs()` en qa_orchestrator.py) — sin `CREATE_NO_WINDOW` acá
    también, Windows le abre una consola nueva a `claude` de la nada (visible,
    en negro porque antes `capture_output=True` mandaba la salida a pipes, no
    a esa ventana) por cada etapa del pipeline."""
    claude = _find_claude_windows() if platform.system() == "Windows" else None
    exe = str(claude) if claude else "claude"
    message = f"Read {prompt_path} and follow it exactly. Output ONLY the JSON object."
    creationflags = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
    argv = [exe, "-p", message]

    live_dir = run_dir / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    live_path = live_dir / f"{stage}.log"

    proc = subprocess.Popen(
        argv,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        shell=False,
        creationflags=creationflags,
        env=_subprocess_env(),
    )

    # Timer separado solo para matar el proceso si se pasa del timeout —
    # no es lectura concurrente de pipes, es la única forma de no bloquear
    # `for line in proc.stdout` indefinidamente si el proceso no imprime
    # nada más pero tampoco termina.
    timed_out = threading.Event()

    def _kill_on_timeout() -> None:
        timed_out.set()
        proc.kill()

    timer = threading.Timer(timeout, _kill_on_timeout)
    timer.daemon = True
    timer.start()
    try:
        chunks: list[str] = []
        with open(live_path, "w", encoding="utf-8") as live_file:
            for line in proc.stdout:
                chunks.append(line)
                live_file.write(line)
                live_file.flush()
        proc.wait()
    finally:
        timer.cancel()

    if timed_out.is_set():
        # Igual que el contrato anterior (subprocess.run con timeout=...):
        # el stdout acumulado se descarta, el llamador ya sabe escribir un
        # resultado de stage-timeout sin necesitarlo.
        raise subprocess.TimeoutExpired(argv, timeout)

    return "".join(chunks)
