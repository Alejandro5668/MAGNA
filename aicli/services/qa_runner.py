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
    VERDICT_SCHEMA,
    _parse_agent_json,
    _read_json_or_none,
    _write_json_atomic,
    _git,
)
from aicli.services.tickets import get_ticket_branch, load_tickets, format_history, _read_ticket

MAX_CORRECTION_ATTEMPTS = 2

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

def run_repro_stage(run_dir: Path, project_path: Path, ticket_id: str, ticket_history: str) -> dict:
    prompt_path = qa_prompts.build_repro_prompt(run_dir, ticket_id, ticket_history)
    defaults = {"steps": [], "expected": None, "actual": None, "evidence": [], "notes": None}
    try:
        stdout = qa_prompts.invoke_stage(prompt_path, project_path)
    except subprocess.TimeoutExpired:
        return _stage_timeout_result(run_dir, "repro", REPRO_SCHEMA, defaults)
    return _finalize_stage_json(run_dir, "repro", REPRO_SCHEMA, stdout, defaults)


# ── Stage: verify ─────────────────────────────────────────────────────────

def run_verify_stage(run_dir: Path, project_path: Path, ticket_id: str, ticket_history: str) -> dict:
    prompt_path = qa_prompts.build_verify_prompt(run_dir, ticket_id, ticket_history)
    defaults = {"checks": [], "evidence": [], "db_reads": []}
    try:
        stdout = qa_prompts.invoke_stage(prompt_path, project_path)
    except subprocess.TimeoutExpired:
        return _stage_timeout_result(run_dir, "verify", VERIFY_SCHEMA, defaults)
    return _finalize_stage_json(run_dir, "verify", VERIFY_SCHEMA, stdout, defaults)


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
        return {"status": "aborted", "reason": "branch_mismatch_or_detached", "commit": None}

    diff_result = _git(["diff", "--", *archivos_tocados], project_path)
    git_diff = diff_result.stdout if diff_result.returncode == 0 else ""

    prompt_path = qa_prompts.build_corrector_prompt(
        run_dir, ticket_id, attempt, MAX_CORRECTION_ATTEMPTS,
        archivos_tocados, git_diff, failure_reason,
    )
    stdout = qa_prompts.invoke_stage(prompt_path, project_path)
    data = _parse_agent_json(stdout)
    if data is None or data.get("status") == "error":
        raw_dir = run_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"correction_{attempt}.txt").write_text(stdout or "", encoding="utf-8")
    motivo = (data or {}).get("motivo") or "correccion automatica"

    if archivos_tocados:
        _git(["add", "--", *archivos_tocados], project_path)
    commit_msg = f"fix(qa-auto): correccion automatica {attempt}/{MAX_CORRECTION_ATTEMPTS} - {motivo}"
    commit_result = _git(["commit", "-m", commit_msg], project_path)
    if commit_result.returncode == 0:
        return {"status": "applied", "commit": commit_msg}
    return {"status": "no_changes", "commit": None}


# ── Agregador — única fuente de qa_verified ───────────────────────────────

def aggregate(*, repro: dict, verify: dict, regression: dict, attempts: int, commits: list[str]) -> dict:
    """Pura Python, sin llamada a LLM (Requirement: Aggregator Sole
    Ownership). Tabla de verdad exacta de design.md:
    - repro not_reproduced ⇒ dudoso (nunca corrección).
    - cualquier stage error ⇒ error.
    - verify pass AND regression in {pass, skipped} ⇒ passed, qa_verified=True.
    - cap de intentos alcanzado ⇒ manual_review.
    - si no, ⇒ failed (el llamador decide si corresponde otro intento)."""
    if repro.get("status") == "not_reproduced":
        return _verdict(False, "dudoso", "repro_not_reproduced", attempts, repro, verify, regression, commits)
    if repro.get("status") == "error":
        return _verdict(False, "error", "repro_stage_error", attempts, repro, verify, regression, commits)
    if verify.get("status") == "error" or regression.get("status") == "error":
        return _verdict(False, "error", "stage_error", attempts, repro, verify, regression, commits)
    if verify.get("status") == "pass" and regression.get("status") in ("pass", "skipped"):
        return _verdict(True, "passed", "verify_pass_regression_ok", attempts, repro, verify, regression, commits)
    if attempts >= MAX_CORRECTION_ATTEMPTS:
        return _verdict(False, "manual_review", "correction_cap_exhausted", attempts, repro, verify, regression, commits)
    return _verdict(False, "failed", "verify_or_regression_fail", attempts, repro, verify, regression, commits)


def _verdict(qa_verified: bool, verdict: str, reason: str, attempts: int,
             repro: dict, verify: dict, regression: dict, commits: list[str]) -> dict:
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


def _write_evidence_log(run_dir: Path, repro: dict, verify: dict, regression: dict, verdict: dict) -> None:
    """Digest plano y legible por humanos del resultado del pipeline —
    Requirement: Evidence Viewable on Demand. `LogScreen` lo muestra tal cual,
    sin necesitar renderizar JSON (ver design.md, sección File Changes)."""
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

    if verdict.get("commits"):
        lines += ["", "Commits de correccion:"]
        lines += [f"  - {c}" for c in verdict["commits"]]

    (run_dir / "evidence.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _finalize(status_path: Path, run_id: str, run_dir: Path, verdict: dict, *,
              repro: dict, verify: dict, regression: dict) -> dict | None:
    status = _still_current(status_path, run_id)
    if status is None:
        return None
    _write_json_atomic(run_dir / "verdict.json", verdict)
    _write_evidence_log(run_dir, repro, verify, regression, verdict)
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
) -> dict | None:
    """Orquesta repro → verify → [regression] → aggregate → [corrector] para
    UNA corrida (`run_id`). Retorna el verdict final, o `None` si la corrida
    fue superseded (design decision 6) antes de terminar — el llamador
    (`qa_cmd.qa_run`) no debe escribir nada más en ese caso."""
    archivos_tocados = files or []

    status = _still_current(status_path, run_id)
    if status is None:
        return None

    status = _advance(status_path, status, state="repro", stage="repro")
    repro = repro_fn(run_dir, project_path, ticket_id, ticket_history)

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

        if verify.get("status") == "pass":
            status = _advance(status_path, status, state="regression", stage="regression")
            regression = regression_fn(run_dir, project_path)
        else:
            regression = {"status": None}

        status = _still_current(status_path, run_id)
        if status is None:
            return None

        verdict = aggregate(repro=repro, verify=verify, regression=regression, attempts=attempt, commits=commits)
        if verdict["verdict"] != "failed":
            return _finalize(
                status_path, run_id, run_dir, verdict,
                repro=repro, verify=verify, regression=regression,
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
