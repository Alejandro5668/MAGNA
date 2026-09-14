"""
Stage driver, agregador y ciclo de corrección del pipeline de QA automático
(Fase 5 del plan SDD). `qa_cmd.qa_run()` invoca `run_pipeline()` en lugar del
loop de heartbeat placeholder de la Fase 3.

Orden de stages: repro → verify → [regression] → aggregate → [corrector].
El agregador (`aggregate()`) es puro Python (Requirement: Aggregator Sole
Ownership) y es el único punto que decide `qa_verified`. El ciclo de
corrección nunca arranca si repro fue `not_reproduced` (Requirement: Never
Correct on Repro Failure) y nunca excede `MAX_CORRECTION_ATTEMPTS` intentos
(Requirement: Bounded Correction Cycles).
"""
import json
import os
import subprocess
import time
from pathlib import Path

from aicli.services import qa_prompts
from aicli.services.qa_orchestrator import (
    REPRO_SCHEMA,
    VERIFY_SCHEMA,
    REGRESSION_SCHEMA,
    REVIEW_SCHEMA,
    VERDICT_SCHEMA,
    BLOCKING_SECURITY_CATEGORIES,
    _parse_agent_json,
    _read_json_or_none,
    _write_json_atomic,
    _git,
    env_preflight,
    clear_env_context,
    _env_text_question,
)
from aicli.services.tickets import get_ticket_branch, load_tickets, format_history, _read_ticket

MAX_CORRECTION_ATTEMPTS = 2
MAX_BLOCKED_REPRO_PAUSES = 1

_TERMINAL_VERDICTS = {"passed", "dudoso", "manual_review", "error"}


# ── Contexto derivado del ticket (files/history no viajan por argv) ──────────

def latest_touched_files(ticket_id: str) -> list[str]:
    """El proceso `qa-run` re-entra solo con ticket_id/project_path/run_id
    (design decision 1) — los archivos tocados por la última corrección se
    re-derivan de la última ronda guardada en el ticket."""
    data = _read_ticket(ticket_id)
    if not data:
        return []
    rondas = data.get("rondas") or []
    if not rondas:
        return []
    return list(rondas[-1].get("archivos_tocados") or [])


def ticket_history_text(ticket_id: str) -> str:
    tickets = load_tickets()
    return format_history(ticket_id, tickets) or ""


# ── Stage: repro ──────────────────────────────────────────────────────────

def run_repro_stage(run_dir: Path, project_path: Path, ticket_id: str, ticket_history: str, env: dict) -> dict:
    prompt_path = qa_prompts.build_repro_prompt(run_dir, ticket_id, ticket_history, env)
    defaults = {
        "steps": [], "expected": None, "actual": None, "evidence": [], "notes": None,
        "blocked_reason": None,
    }
    try:
        stdout = qa_prompts.invoke_stage(prompt_path, project_path, run_dir=run_dir, stage="repro")
    except subprocess.TimeoutExpired:
        return _stage_timeout_result(run_dir, "repro", REPRO_SCHEMA, defaults)
    return _finalize_stage_json(run_dir, "repro", REPRO_SCHEMA, stdout, defaults)


# ── Stage: verify ─────────────────────────────────────────────────────────

def run_verify_stage(run_dir: Path, project_path: Path, ticket_id: str, ticket_history: str) -> dict:
    prompt_path = qa_prompts.build_verify_prompt(run_dir, ticket_id, ticket_history)
    defaults = {"checks": [], "evidence": [], "db_reads": [], "needs_input": None}
    try:
        stdout = qa_prompts.invoke_stage(prompt_path, project_path, run_dir=run_dir, stage="verify")
    except subprocess.TimeoutExpired:
        return _stage_timeout_result(run_dir, "verify", VERIFY_SCHEMA, defaults)
    return _finalize_stage_json(run_dir, "verify", VERIFY_SCHEMA, stdout, defaults)


def _repro_blocked(repro: dict) -> str | None:
    """Retorna el `blocked_reason` SOLO cuando el agente de repro marcó
    explícitamente `status: "blocked"` (bloqueo de entorno detectado a
    mitad de un intento) — `run_pipeline()` usa esto para decidir si vale
    la pena re-preguntar DB/URL por el canal de entorno (design decision
    11). El caso `not_reproduced` con `steps` vacío es una normalización
    DISTINTA que vive dentro de `aggregate()` (nunca amerita una nueva
    pregunta de entorno — no hay evidencia de que el entorno sea el
    problema, solo de que no se intentó)."""
    if repro.get("status") == "blocked":
        return repro.get("blocked_reason") or "bloqueado por el agente de repro"
    return None


def _stage_timeout_result(run_dir: Path, stage: str, schema: str, defaults: dict) -> dict:
    """Un `subprocess.TimeoutExpired` de `invoke_stage` nunca debe propagar y
    tumbar el pipeline completo — se normaliza al mismo `status:"error"` que
    ya usa el JSON inparseable (design.md: 'Any stage error/timeout ⇒
    error'), así el agregador lo trata exactamente igual que cualquier otro
    error de stage sin necesitar un status "timeout" literal en el esquema."""
    result = {"schema": schema, "status": "error", "error": "stage_timeout", **defaults}
    _write_json_atomic(run_dir / f"{stage}.json", result)
    return result


def _finalize_stage_json(run_dir: Path, stage: str, schema: str, stdout: str, defaults: dict) -> dict:
    """Parseo defensivo compartido por repro/verify: JSON inválido/vacío
    nunca cuenta como pass — se escribe como stage error y el stdout crudo se
    conserva para diagnóstico (Requirement: Malformed stage JSON never counts
    as a pass)."""
    data = _parse_agent_json(stdout)
    if data is None:
        raw_dir = run_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"{stage}.txt").write_text(stdout or "", encoding="utf-8")
        result = {"schema": schema, "status": "error", "error": "unparseable_output", **defaults}
    else:
        result = {**defaults, **data}
        result["schema"] = schema
        result.setdefault("error", None)
    _write_json_atomic(run_dir / f"{stage}.json", result)
    return result


# ── Stage: regression ─────────────────────────────────────────────────────

def run_regression_stage(run_dir: Path, project_path: Path) -> dict:
    """`npx playwright test` en un repo E2E separado (design decision —
    regression re-runs spend zero LLM tokens). `status:"skipped"` cuando
    `MAGNA_E2E_REPO` no está seteada — bootstrap-friendly default confirmado
    con el usuario (ver design.md §5.2). NOTA DE ALCANCE: el parseo del
    reporte JSON de Playwright de esta unidad es un stub razonable sobre la
    forma documentada de `--reporter=json`; la integración completa contra un
    repo Playwright real queda fuera del alcance de esta unidad (Fase 4+5)."""
    e2e_repo = os.environ.get("MAGNA_E2E_REPO")
    if not e2e_repo:
        result = {
            "schema": REGRESSION_SCHEMA, "status": "skipped", "total": 0,
            "passed": 0, "failed": 0, "failures": [], "report_path": None, "error": None,
        }
        _write_json_atomic(run_dir / "regression.json", result)
        return result

    report_path = run_dir / "playwright-report.json"
    try:
        proc = subprocess.run(
            ["npx", "playwright", "test", "--reporter=json"],
            cwd=str(e2e_repo), capture_output=True, text=True, shell=False,
            timeout=qa_prompts.STAGE_TIMEOUT_SECONDS,
        )
        report_path.write_text(proc.stdout or "", encoding="utf-8")
        stats = {}
        try:
            stats = (json.loads(proc.stdout) if proc.stdout.strip() else {}).get("stats", {})
        except json.JSONDecodeError:
            stats = {}
        expected = stats.get("expected", 0)
        unexpected = stats.get("unexpected", 0)
        status = "pass" if proc.returncode == 0 else "fail"
        result = {
            "schema": REGRESSION_SCHEMA, "status": status,
            "total": expected + unexpected, "passed": expected, "failed": unexpected,
            "failures": [], "report_path": str(report_path), "error": None,
        }
    except Exception as exc:
        result = {
            "schema": REGRESSION_SCHEMA, "status": "error", "total": 0, "passed": 0,
            "failed": 0, "failures": [], "report_path": None, "error": str(exc),
        }
    _write_json_atomic(run_dir / "regression.json", result)
    return result


# ── Stage: review (combinado seguridad + calidad) ─────────────────────────

_REVIEW_BASE_BRANCHES = ("main", "master", "develop")


def _review_diff(project_path: Path, archivos_tocados: list[str]) -> str:
    """Diff de SOLO los archivos tocados por la corrección — nunca el repo
    completo (threat matrix: diff scope blowout). Lista vacía ⇒ `""` sin
    ninguna llamada a git. Base resuelta vía `merge-base` read-only sobre
    `("main","master","develop")`; si ninguna resuelve, cae a un diff
    contra el working tree (sin base) — nunca compara contra un remoto ni
    cambia de branch. Todo pasa por `_git()` (siempre `cwd=project_path`,
    siempre list-argv, siempre un comando fuera del deny-list: solo
    `merge-base`/`diff`)."""
    if not archivos_tocados:
        return ""
    for base_branch in _REVIEW_BASE_BRANCHES:
        merge_base = _git(["merge-base", "HEAD", base_branch], project_path)
        sha = merge_base.stdout.strip() if merge_base.returncode == 0 else ""
        if not sha:
            continue
        diff_result = _git(["diff", sha, "--", *archivos_tocados], project_path)
        if diff_result.returncode == 0:
            return diff_result.stdout
    diff_result = _git(["diff", "--", *archivos_tocados], project_path)
    return diff_result.stdout if diff_result.returncode == 0 else ""


def run_review_stage(run_dir: Path, project_path: Path, ticket_id: str, archivos_tocados: list[str]) -> dict:
    """Requirement: Review Stage Contract. Lee ÚNICAMENTE el diff de la
    corrección y los archivos tocados — nunca el repo completo. Una lista
    vacía de `archivos_tocados` es un short-circuit total: cero llamadas a
    `claude -p`, `status:"skipped"` con cero findings (el veredicto puede
    seguir siendo `passed` — Requirement scenario 'diff scope blowout')."""
    defaults = {"security": {"findings": []}, "quality": {"findings": []}}
    if not archivos_tocados:
        result = {"schema": REVIEW_SCHEMA, "status": "skipped", "error": None, **defaults}
        _write_json_atomic(run_dir / "review.json", result)
        return result

    git_diff = _review_diff(project_path, archivos_tocados)
    prompt_path = qa_prompts.build_review_prompt(run_dir, ticket_id, archivos_tocados, git_diff)
    try:
        stdout = qa_prompts.invoke_stage(prompt_path, project_path, run_dir=run_dir, stage="review")
    except subprocess.TimeoutExpired:
        return _stage_timeout_result(run_dir, "review", REVIEW_SCHEMA, defaults)
    return _finalize_stage_json(run_dir, "review", REVIEW_SCHEMA, stdout, defaults)


def _review_applies(verify: dict, regression: dict) -> bool:
    """`review` corre UNA vez, solo en el único camino que puede producir
    `passed` (design decision 12) — evaluado DESPUÉS de regression, nunca
    justo después de verify: pass (verify puede pasar y regression seguir
    fallando, lo que reintenta la corrección; correr review ahí gastaría
    hasta 3 invocaciones de 600s por ticket en vez de máximo 1)."""
    return verify.get("status") == "pass" and regression.get("status") in ("pass", "skipped")


def _blocking_security_findings(review: dict) -> list[dict]:
    """Requirement: Aggregator Sole Ownership / Review Stage Contract.
    Única fuente de autoridad para "esto bloquea": la `category` normalizada
    contra `BLOCKING_SECURITY_CATEGORIES`, un allowlist cerrado — el
    `severity` que reporte el agente es decorativo y NUNCA se lee acá
    (design decision 13). Una categoría inventada o fuera del allowlist
    jamás bloquea, sin importar qué severidad le haya puesto el agente."""
    findings = ((review.get("security") or {}).get("findings")) or []
    return [
        f for f in findings
        if isinstance(f, dict) and str(f.get("category", "")).strip().lower() in BLOCKING_SECURITY_CATEGORIES
    ]


# ── Corrección: pre-flight de branch + edición + commit ──────────────────

def run_correction_attempt(
    *,
    run_dir: Path,
    project_path: Path,
    ticket_id: str,
    attempt: int,
    archivos_tocados: list[str],
    failure_reason: str,
    branch: str | None,
) -> dict:
    """Un intento de corrección: pre-flight de branch (design decision 7 —
    mismatch/detached HEAD aborta a manual_review, NUNCA cambia de branch),
    invocación headless del corrector (file-scoped) y commit vía `_git`
    (pathspec explícito, nunca `-A`/`-a`). Nunca propaga una excepción — una
    falla de git/parseo se refleja en el dict retornado."""
    current = _git(["rev-parse", "--abbrev-ref", "HEAD"], project_path)
    current_branch = current.stdout.strip()
    expected_branch = branch or get_ticket_branch(ticket_id)
    if (
        current.returncode != 0
        or current_branch in ("", "HEAD")
        or (expected_branch and current_branch != expected_branch)
    ):
        return {"status": "aborted", "reason": "branch_mismatch_or_detached", "commit": None, "needs_input": None}

    diff_result = _git(["diff", "--", *archivos_tocados], project_path)
    git_diff = diff_result.stdout if diff_result.returncode == 0 else ""

    prompt_path = qa_prompts.build_corrector_prompt(
        run_dir, ticket_id, attempt, MAX_CORRECTION_ATTEMPTS,
        archivos_tocados, git_diff, failure_reason,
    )
    stdout = qa_prompts.invoke_stage(
        prompt_path, project_path, run_dir=run_dir, stage=f"correction_{attempt}",
    )
    data = _parse_agent_json(stdout)
    if data is None or data.get("status") == "error":
        raw_dir = run_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"correction_{attempt}.txt").write_text(stdout or "", encoding="utf-8")
    motivo = (data or {}).get("motivo") or "correccion automatica"
    needs_input = (data or {}).get("needs_input")

    if needs_input:
        # El agente detectó que necesita DB/URL que no puede inferir (o
        # confirmar) — se detiene ANTES de commitear, en vez de forzar un
        # commit sobre un intento incompleto (Requirement: needs_input
        # escape hatch, ver brief).
        return {"status": "awaiting_input", "commit": None, "needs_input": needs_input}

    if archivos_tocados:
        _git(["add", "--", *archivos_tocados], project_path)
    commit_msg = f"fix(qa-auto): correccion automatica {attempt}/{MAX_CORRECTION_ATTEMPTS} - {motivo}"
    commit_result = _git(["commit", "-m", commit_msg], project_path)
    if commit_result.returncode == 0:
        return {"status": "applied", "commit": commit_msg, "needs_input": None}
    return {"status": "no_changes", "commit": None, "needs_input": None}


# ── Agregador — única fuente de qa_verified ───────────────────────────────

def aggregate(*, repro: dict, verify: dict, regression: dict, attempts: int, commits: list[str],
              review: dict | None = None) -> dict:
    """Pura Python, sin llamada a LLM (Requirement: Aggregator Sole
    Ownership). Tabla de verdad exacta de design.md:
    - repro not_reproduced con steps[] no vacío ⇒ dudoso (nunca corrección).
    - repro not_reproduced con steps[] vacío ⇒ manual_review (normalizado —
      sin evidencia de intento, dudoso nunca es alcanzable, decision 11).
    - repro blocked (bound de re-preguntas agotado) ⇒ manual_review.
    - cualquier stage error ⇒ error.
    - verify pass AND regression in {pass, skipped}:
        - review error ⇒ manual_review (alguien tiene que revisar a mano).
        - hallazgo de seguridad bloqueante en review ⇒ manual_review.
        - si no ⇒ passed, qa_verified=True.
    - cap de intentos alcanzado ⇒ manual_review.
    - si no, ⇒ failed (el llamador decide si corresponde otro intento)."""
    if repro.get("status") == "not_reproduced" and not (repro.get("steps") or []):
        return _verdict(
            False, "manual_review", "repro_no_attempt_evidence", attempts, repro, verify, regression, commits,
        )
    if repro.get("status") == "not_reproduced":
        return _verdict(False, "dudoso", "repro_not_reproduced", attempts, repro, verify, regression, commits)
    if repro.get("status") == "blocked":
        return _verdict(False, "manual_review", "repro_blocked", attempts, repro, verify, regression, commits)
    if repro.get("status") == "error":
        return _verdict(False, "error", "repro_stage_error", attempts, repro, verify, regression, commits)
    if verify.get("status") == "error" or regression.get("status") == "error":
        return _verdict(False, "error", "stage_error", attempts, repro, verify, regression, commits)
    if verify.get("status") == "pass" and regression.get("status") in ("pass", "skipped"):
        if review is not None and review.get("status") == "error":
            return _verdict(
                False, "manual_review", "review_stage_error", attempts, repro, verify, regression, commits,
                review=review,
            )
        if review is not None and _blocking_security_findings(review):
            return _verdict(
                False, "manual_review", "security_finding_severe", attempts, repro, verify, regression, commits,
                review=review,
            )
        return _verdict(
            True, "passed", "verify_pass_regression_ok", attempts, repro, verify, regression, commits,
            review=review,
        )
    if attempts >= MAX_CORRECTION_ATTEMPTS:
        return _verdict(False, "manual_review", "correction_cap_exhausted", attempts, repro, verify, regression, commits)
    return _verdict(False, "failed", "verify_or_regression_fail", attempts, repro, verify, regression, commits)


def _verdict(qa_verified: bool, verdict: str, reason: str, attempts: int,
             repro: dict, verify: dict, regression: dict, commits: list[str],
             review: dict | None = None) -> dict:
    return {
        "schema": VERDICT_SCHEMA,
        "qa_verified": qa_verified,
        "verdict": verdict,
        "reason": reason,
        "attempts": attempts,
        "stages": {
            "repro": repro.get("status"),
            "verify": verify.get("status"),
            "regression": regression.get("status"),
            "review": (review or {}).get("status"),
        },
        "commits": commits,
        "finished_at": time.time(),
    }


def _first_failed_detail(verify: dict) -> str | None:
    for check in verify.get("checks", []) or []:
        if check.get("result") == "fail":
            return check.get("detail") or check.get("name")
    return None


# ── Supersede cooperativo (design decision 6) ─────────────────────────────

def _still_current(status_path: Path, run_id: str) -> dict | None:
    status = _read_json_or_none(status_path)
    if status is None or status.get("run_id") != run_id:
        return None
    return status


def _advance(status_path: Path, status: dict, *, state: str | None = None,
             stage: str | None = None, event: tuple[str, str] | None = None) -> dict:
    if state is not None:
        status["state"] = state
    if stage is not None:
        status["stage"] = stage
    if event is not None:
        kind, msg = event
        seq = (status["events"][-1]["seq"] + 1) if status["events"] else 1
        status["events"].append({"seq": seq, "ts": time.time(), "kind": kind, "msg": msg})
    status["heartbeat"] = time.time()
    _write_json_atomic(status_path, status)
    return status


def _write_evidence_log(run_dir: Path, repro: dict, verify: dict, regression: dict, verdict: dict,
                         review: dict | None = None) -> None:
    """Digest plano y legible por humanos del resultado del pipeline —
    Requirement: Evidence Viewable on Demand. `LogScreen` lo muestra tal cual,
    sin necesitar renderizar JSON (ver design.md, sección File Changes).
    Requirement: Review Findings in Evidence Digest — `security`/`quality`
    se listan tal cual, ambos como texto plano; ninguno introduce un badge
    nuevo (eso lo decide únicamente `read_qa_badge`, no este digest)."""
    lines = [
        f"Veredicto: {verdict.get('verdict')} (qa_verified={verdict.get('qa_verified')})",
        f"Motivo: {verdict.get('reason')}",
        f"Intentos de correccion: {verdict.get('attempts', 0)}",
        "",
        f"[Repro] status={repro.get('status')}",
    ]
    if repro.get("expected") or repro.get("actual"):
        lines.append(f"  esperado: {repro.get('expected')}")
        lines.append(f"  actual:   {repro.get('actual')}")
    if repro.get("notes"):
        lines.append(f"  notas: {repro.get('notes')}")

    lines += ["", f"[Verify] status={verify.get('status')}"]
    for check in verify.get("checks") or []:
        lines.append(f"  - {check.get('name')}: {check.get('result')} ({check.get('detail') or ''})")

    lines += ["", f"[Regression] status={regression.get('status')}"]
    if regression.get("total"):
        lines.append(
            f"  total={regression.get('total')} passed={regression.get('passed')} "
            f"failed={regression.get('failed')}"
        )
    for failure in regression.get("failures") or []:
        lines.append(f"  - {failure.get('test')}: {failure.get('message')}")

    if review is not None:
        lines += ["", f"[Review] status={review.get('status')}"]
        for finding in ((review.get("security") or {}).get("findings")) or []:
            lines.append(
                f"  - [security:{finding.get('category')}] "
                f"{finding.get('file')}:{finding.get('line')} — {finding.get('detail')} "
                f"(severity={finding.get('severity')})"
            )
        for finding in ((review.get("quality") or {}).get("findings")) or []:
            lines.append(
                f"  - [quality:{finding.get('kind')}] "
                f"{finding.get('file')}:{finding.get('line')} — {finding.get('detail')}"
            )

    if verdict.get("commits"):
        lines += ["", "Commits de correccion:"]
        lines += [f"  - {c}" for c in verdict["commits"]]

    (run_dir / "evidence.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _finalize_awaiting_input(status_path: Path, run_id: str, needs_input: dict) -> dict | None:
    """Pausa la corrida: escribe `state:"awaiting_input"` + la pregunta en
    `status.json`, en vez de agregar/finalizar como pass/fail. Distinto tanto
    de "sigue corriendo" como de los veredictos terminales existentes
    (`_TERMINAL_VERDICTS`) — no se escribe `verdict.json`, así que ningún
    consumidor puede confundirlo con un veredicto real. Retorna `None` si la
    corrida fue superseded en el ínterin (mismo contrato que `_finalize`)."""
    status = _still_current(status_path, run_id)
    if status is None:
        return None
    status["question"] = needs_input
    return _advance(
        status_path, status, state="awaiting_input", stage="awaiting_input",
        event=("awaiting_input", f"Esperando respuesta del usuario: {needs_input.get('prompt')}"),
    )


def _finalize(status_path: Path, run_id: str, run_dir: Path, verdict: dict, *,
              repro: dict, verify: dict, regression: dict, review: dict | None = None) -> dict | None:
    status = _still_current(status_path, run_id)
    if status is None:
        return None
    _write_json_atomic(run_dir / "verdict.json", verdict)
    _write_evidence_log(run_dir, repro, verify, regression, verdict, review=review)
    terminal_state = "error" if verdict["verdict"] == "error" else "done"
    _advance(
        status_path, status, state=terminal_state, stage="verdict",
        event=("terminal", f"Verdict: {verdict['verdict']} (qa_verified={verdict['qa_verified']})"),
    )
    return verdict


# ── Orquestación completa ──────────────────────────────────────────────────

def run_pipeline(
    *,
    ticket_id: str,
    project_path: Path,
    run_dir: Path,
    run_id: str,
    status_path: Path,
    ticket_history: str = "",
    files: list[str] | None = None,
    branch: str | None = None,
    repro_fn=run_repro_stage,
    verify_fn=run_verify_stage,
    regression_fn=run_regression_stage,
    correction_fn=run_correction_attempt,
    review_fn=run_review_stage,
) -> dict | None:
    """Orquesta repro → verify → [regression] → aggregate → [corrector] para
    UNA corrida (`run_id`). Retorna el verdict final, o `None` si la corrida
    fue superseded (design decision 6) antes de terminar — el llamador
    (`qa_cmd.qa_run`) no debe escribir nada más en ese caso."""
    archivos_tocados = files or []

    status = _still_current(status_path, run_id)
    if status is None:
        return None

    # Pre-flight de entorno (design decision 9) — antes de CUALQUIER stage.
    # Puro Python, 0 tokens: confirma el DB/URL del ticket exactamente una
    # vez y lo reusa en corridas siguientes (Requirement: Pre-Flight DB/URL
    # Confirmation). Si todavía no hay contexto confirmado, pausa igual que
    # cualquier otro needs_input — nunca arranca repro sin él.
    env, env_question = env_preflight(run_dir, ticket_id)
    if env_question is not None:
        return _finalize_awaiting_input(status_path, run_id, env_question)

    status = _advance(status_path, status, state="repro", stage="repro")
    repro = repro_fn(run_dir, project_path, ticket_id, ticket_history, env)

    blocked_reason = _repro_blocked(repro)
    if blocked_reason is not None:
        pauses = status.get("repro_blocked_pauses", 0)
        if pauses < MAX_BLOCKED_REPRO_PAUSES:
            # Bloqueo de entorno a mitad de intento (design decision 11):
            # re-pregunta DB/URL por el MISMO canal de env, acotado a
            # MAX_BLOCKED_REPRO_PAUSES — nunca un loop indefinido de
            # preguntas. `repro_blocked_pauses` viaja en status.json y
            # `resume_qa()` ya lo preserva vía su merge `{**status, ...}`.
            clear_env_context(run_dir)
            status["repro_blocked_pauses"] = pauses + 1
            _write_json_atomic(status_path, status)
            question = {**_env_text_question(ticket_id), "blocked_reason": blocked_reason}
            return _finalize_awaiting_input(status_path, run_id, question)
        # Bound agotado: cae al agregador como manual_review/repro_blocked
        # — nunca dudoso, nunca una corrección (Requirement: Never Correct
        # on Repro Failure).
        verify_empty, regression_empty = {"status": None}, {"status": None}
        verdict = aggregate(
            repro=repro, verify=verify_empty, regression=regression_empty, attempts=0, commits=[],
        )
        return _finalize(
            status_path, run_id, run_dir, verdict,
            repro=repro, verify=verify_empty, regression=regression_empty,
        )

    if repro.get("status") in ("not_reproduced", "error"):
        verify_empty, regression_empty = {"status": None}, {"status": None}
        verdict = aggregate(
            repro=repro, verify=verify_empty, regression=regression_empty,
            attempts=0, commits=[],
        )
        return _finalize(
            status_path, run_id, run_dir, verdict,
            repro=repro, verify=verify_empty, regression=regression_empty,
        )

    status = _still_current(status_path, run_id)
    if status is None:
        return None

    commits: list[str] = []
    attempt = 0

    while True:
        status = _advance(status_path, status, state="verify", stage="verify")
        verify = verify_fn(run_dir, project_path, ticket_id, ticket_history)

        status = _still_current(status_path, run_id)
        if status is None:
            return None

        needs_input = verify.get("needs_input")
        if needs_input:
            return _finalize_awaiting_input(status_path, run_id, needs_input)

        if verify.get("status") == "pass":
            status = _advance(status_path, status, state="regression", stage="regression")
            regression = regression_fn(run_dir, project_path)
        else:
            regression = {"status": None}

        status = _still_current(status_path, run_id)
        if status is None:
            return None

        # Review corre UNA sola vez, solo en el único camino que puede
        # producir "passed" (design decision 12) — nunca si verify o
        # regression todavía pueden reintentar vía corrección.
        review = None
        if _review_applies(verify, regression):
            status = _advance(status_path, status, state="review", stage="review")
            review = review_fn(run_dir, project_path, ticket_id, archivos_tocados)

        status = _still_current(status_path, run_id)
        if status is None:
            return None

        verdict = aggregate(
            repro=repro, verify=verify, regression=regression, attempts=attempt, commits=commits, review=review,
        )
        if verdict["verdict"] != "failed":
            return _finalize(
                status_path, run_id, run_dir, verdict,
                repro=repro, verify=verify, regression=regression, review=review,
            )

        attempt += 1
        failure_reason = verify.get("error") or _first_failed_detail(verify) or "verificacion fallida"
        status = _advance(
            status_path, status, state="correcting", stage=f"correction_{attempt}",
            event=("correction", f"Iniciando correccion {attempt}/{MAX_CORRECTION_ATTEMPTS}"),
        )
        result = correction_fn(
            run_dir=run_dir, project_path=project_path, ticket_id=ticket_id,
            attempt=attempt, archivos_tocados=archivos_tocados,
            failure_reason=failure_reason, branch=branch,
        )
        if result.get("commit"):
            commits.append(result["commit"])

        status = _still_current(status_path, run_id)
        if status is None:
            return None

        needs_input = result.get("needs_input")
        if needs_input:
            return _finalize_awaiting_input(status_path, run_id, needs_input)

        if result.get("status") == "aborted":
            verdict = aggregate(
                repro=repro, verify=verify, regression=regression,
                attempts=MAX_CORRECTION_ATTEMPTS, commits=commits,
            )
            verdict["reason"] = result.get("reason", "correction_aborted")
            return _finalize(
                status_path, run_id, run_dir, verdict,
                repro=repro, verify=verify, regression=regression,
            )
        # loop: re-verifica con el estado post-correccion
