"""
Punto de re-entrada oculto del pipeline de QA automático — lanzado como
proceso OS detached por `qa_orchestrator.trigger_qa()` (Fase 3 del plan SDD).

Esta unidad de trabajo NO ejecuta los stages reales del pipeline
(repro/verify/regression/corrector, Fase 5) — únicamente prueba el mecanismo
de detach: escribe heartbeats periódicos en `status.json` y termina en
`state:"done"`, respetando el supersede cooperativo (si `status.json` ya
tiene otro `run_id`, esta corrida se sabe reemplazada y sale sin escribir
nada). Esto permite verificar el lanzador de punta a punta sin depender de
la lógica de stages, todavía no implementada.
"""
import time

import typer

from aicli.services.qa_orchestrator import _read_json_or_none, _run_dir, _write_json_atomic

app = typer.Typer()

# Placeholder de esta unidad — Fase 5 reemplaza este loop por la secuencia
# real de stages (repro → verify → regression → aggregate → [corrector]).
_HEARTBEAT_INTERVAL_SECONDS = 0.2
_PLACEHOLDER_HEARTBEAT_TICKS = 3


@app.callback(invoke_without_command=True)
def qa_run(
    ticket_id: str = typer.Argument(..., help="Ticket sobre el que corre el pipeline de QA"),
    project_path: str = typer.Option(..., "--project-path", help="Ruta del proyecto a verificar"),
    run_id: str = typer.Option(..., "--run-id", help="run_id que este proceso debe honrar"),
):
    """[oculto] Re-entrada del pipeline de QA — no invocar manualmente."""
    run_dir = _run_dir(ticket_id)
    status_path = run_dir / "status.json"

    for _ in range(_PLACEHOLDER_HEARTBEAT_TICKS):
        status = _read_json_or_none(status_path)
        if status is None or status.get("run_id") != run_id:
            # Supersede cooperativo (design decision 6): una corrida más
            # nueva ya reemplazó a esta — salir sin tocar nada.
            return
        status["heartbeat"] = time.time()
        _write_json_atomic(status_path, status)
        time.sleep(_HEARTBEAT_INTERVAL_SECONDS)

    status = _read_json_or_none(status_path)
    if status is None or status.get("run_id") != run_id:
        return
    status["state"] = "done"
    status["heartbeat"] = time.time()
    _write_json_atomic(status_path, status)
