# qa-orchestrator Specification

## Purpose

Trigger and process-lifecycle contract for the QA pipeline: a non-blocking
launch point, a detached subprocess that outlives its caller, and a
per-ticket blackboard directory that stages read/write evidence through.

## Requirements

### Requirement: Non-Blocking Trigger Point

The system MUST launch the QA pipeline from exactly one call site inside
`_sync_impl`, placed after `save_round` and inside the `if save:` branch, and
MUST NOT block `ctx sync`'s return on pipeline completion.

#### Scenario: Sync returns before QA finishes

- GIVEN a ticket round is saved via `ctx sync`
- WHEN the QA trigger fires
- THEN `ctx sync` returns to the shell within its normal runtime, unaffected by QA duration

### Requirement: Detached Process Lifetime

The system MUST launch QA stages as a detached OS process (one launcher
mechanism shared by CLI and TUI call sites) that continues running after the
parent terminal or TUI session exits.

#### Scenario: Pipeline survives terminal close

- GIVEN the QA pipeline has started for a ticket
- WHEN the user closes the terminal that ran `ctx sync`
- THEN the pipeline continues to completion and writes its terminal evidence file

### Requirement: Blackboard Directory Layout

The system MUST persist all stage evidence as JSON files under
`~/.mycontext/qa_results/<TICKET>/`, one file per stage plus a heartbeat/PID
file, with no other cross-process communication channel.

#### Scenario: Evidence readable after the fact

- GIVEN a QA run completed for `PROJ-100`
- WHEN a reader inspects `~/.mycontext/qa_results/PROJ-100/`
- THEN each stage's evidence JSON and the aggregator's terminal state are present as files

### Requirement: Supersede on Re-Sync

WHEN a new `ctx sync` triggers a QA run for a ticket that already has a run
in progress, the system MUST supersede the old run: discard its partial
artifacts and start fresh, never merge partial state across runs.

#### Scenario: Re-sync during an active run

- GIVEN a QA run for `PROJ-100` is in progress
- WHEN the user runs `ctx sync` again for `PROJ-100` before it finishes
- THEN the old run's partial artifacts are discarded and a new run starts from stage one
