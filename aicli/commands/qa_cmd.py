"""
Punto de re-entrada oculto del pipeline de QA automático — lanzado como
proceso OS detached por `qa_orchestrator.trigger_qa()` (Fase 3 del plan SDD).

Fase 5 (esta unidad): reemplaza el loop de heartbeat placeholder de la Fase 3
por la secuencia real de stages — repro → verify → [regression] → aggregate
→ [corrector] — delegada a `qa_runner.run_pipeline()`. El supersede
cooperativo (design decision 6) se sigue respetando: si `status.json` ya
tiene otro `run_id` en cualquier punto, el pipeline aborta sin escribir
`verdict.json` ni tocar `status.json` de nuevo.
"""
from pathlib import Path

import typer

from aicli.services import qa_runner
from aicli.services.qa_orchestrator import _read_json_or_none, _run_dir

app = typer.Typer()


@app.callback(invoke_without_command=True)
def qa_run(
    ticket_id: str = typer.Argument(..., help="Ticket sobre el que corre el pipeline de QA"),
    project_path: str = typer.Option(..., "--project-path", help="Ruta del proyecto a verificar"),
    run_id: str = typer.Option(..., "--run-id", help="run_id que este proceso debe honrar"),
):
    """[oculto] Re-entrada del pipeline de QA — no invocar manualmente."""
    run_dir = _run_dir(ticket_id)
    status_path = run_dir / "status.json"

    status = _read_json_or_none(status_path)
    if status is None or status.get("run_id") != run_id:
        # Supersede cooperativo (design decision 6): una corrida más nueva
        # ya reemplazó a esta antes de arrancar — salir sin tocar nada.
        return

    qa_runner.run_pipeline(
        ticket_id=ticket_id,
        project_path=Path(project_path),
        run_dir=run_dir,
        run_id=run_id,
        status_path=status_path,
        ticket_history=qa_runner.ticket_history_text(ticket_id),
        files=qa_runner.latest_touched_files(ticket_id),
        branch=status.get("branch"),
    )
