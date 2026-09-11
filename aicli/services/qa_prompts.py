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
import platform
import subprocess
from pathlib import Path

from aicli.services.caller import _find_claude_windows

STAGE_TIMEOUT_SECONDS = 600

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
    + acceso de SOLO LECTURA a base de datos; nunca una escritura de
    producción."""
    content = f"""# Rol: QA Verify Agent

Tu tarea es re-intentar, con un navegador real, los mismos pasos del bug
reportado para el ticket {ticket_id}. Si necesitás confirmar estado en base
de datos, tenés acceso de SOLO LECTURA — NUNCA hagas una escritura de
producción (ni DB ni API).

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
  "error": null
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
  "error": null
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
