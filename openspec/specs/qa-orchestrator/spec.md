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
artifacts and start fresh, never merge partial state across runs. The
ticket's persisted DB/URL confirmation MUST survive supersede and MUST NOT
be discarded with the other stage artifacts.

#### Scenario: Re-sync during an active run

- GIVEN a QA run for `PROJ-100` is in progress
- WHEN the user runs `ctx sync` again for `PROJ-100` before it finishes
- THEN the old run's partial artifacts are discarded and a new run starts from stage one

#### Scenario: Persisted DB choice survives supersede

- GIVEN `PROJ-100` has a persisted DB/URL confirmation from an earlier run
- WHEN a new run supersedes the in-progress one
- THEN the new run reuses the persisted DB/URL choice without re-asking

### Requirement: Pre-Flight DB/URL Confirmation

The system MUST confirm the DB/URL to use for a ticket exactly once per
ticket, before any stage runs, using the existing `needs_input` /
`answer.json` / `resume_qa` pause mechanism. The confirmed choice MUST be
persisted keyed by ticket and MUST be reused (never re-asked) across
subsequent runs for that ticket — resyncs and correction retries — unless
the user changes it.

#### Scenario: First run for a ticket asks once

- GIVEN a ticket has no persisted DB/URL choice
- WHEN its first QA run starts
- THEN the pipeline pauses via `_finalize_awaiting_input` before any stage
  executes and waits for `resume_qa` to supply the DB/URL answer

#### Scenario: Subsequent run reuses the persisted answer

- GIVEN a ticket already has a persisted DB/URL choice from a prior run
- WHEN a new run starts for that same ticket (resync or correction retry)
- THEN the pipeline proceeds directly to stage execution without pausing to
  ask again
