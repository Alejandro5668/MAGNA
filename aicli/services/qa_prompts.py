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
from pathlib import Path

from aicli.services.caller import _find_claude_windows
from aicli.services.qa_orchestrator import _read_json_or_none

STAGE_TIMEOUT_SECONDS = 600

_NO_CONFIGURADA = "(no configurada)"


def _default_db_hint() -> str:
    return os.environ.get("MAGNA_QA_DEFAULT_DB") or _NO_CONFIGURADA


def _default_url_hint() -> str:
    return os.environ.get("MAGNA_QA_APP_URL") or _NO_CONFIGURADA


def _consume_answer(run_dir: Path) -> str | None:
    """Lee `run_dir/answer.json` (escrito por
    `qa_orchestrator.write_qa_answer` antes de un resume) y lo borra de
    inmediato — read-and-consume, para que un resume posterior no relacionado
    con esta pregunta nunca reuse una respuesta vieja."""
    path = run_dir / "answer.json"
    data = _read_json_or_none(path)
    if data is None:
        return None
    path.unlink(missing_ok=True)
    return data.get("value")


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


def build_repro_prompt(run_dir: Path, ticket_id: str, ticket_history: str) -> Path:
    """Prompt de repro — Requirement: Repro Stage Isolation. SOLO recibe el
    reporte/historial original del ticket; NUNCA debe contener ninguna
    referencia al diff de la corrección, al mensaje de commit, ni a que un
    fix ya fue aplicado."""
    content = f"""# Rol: QA Repro Agent

Tu única tarea es intentar reproducir el bug reportado para el ticket
{ticket_id}, usando EXCLUSIVAMENTE el reporte/historial de abajo. No busques
ni asumas ningún cambio de código relacionado — actuá como si no supieras
si el proyecto ya fue modificado para atender este reporte.

## Reporte / historial del ticket

{ticket_history or "(sin historial adicional)"}

## Qué hacer

1. Intentá reproducir el bug siguiendo los pasos reportados.
2. Registrá los pasos que seguiste, el resultado esperado y el resultado real.

## Formato de salida — ÚNICAMENTE este JSON, sin texto adicional

{{
  "schema": "qa.repro/1",
  "status": "reproduced" | "not_reproduced",
  "steps": ["paso 1", "paso 2"],
  "expected": "...",
  "actual": "...",
  "evidence": [],
  "notes": "..."
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


def invoke_stage(prompt_path: Path, cwd: Path, timeout: int = STAGE_TIMEOUT_SECONDS) -> str:
    """Invoca `claude -p` headless apuntando al archivo de prompt (nunca el
    contenido completo por argv). Retorna stdout crudo; el llamador es
    responsable de parsearlo vía `qa_orchestrator._parse_agent_json()`.
    Nunca `shell=True`; siempre list-argv."""
    claude = _find_claude_windows() if platform.system() == "Windows" else None
    exe = str(claude) if claude else "claude"
    message = f"Read {prompt_path} and follow it exactly. Output ONLY the JSON object."
    result = subprocess.run(
        [exe, "-p", message],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        shell=False,
        timeout=timeout,
    )
    return result.stdout
