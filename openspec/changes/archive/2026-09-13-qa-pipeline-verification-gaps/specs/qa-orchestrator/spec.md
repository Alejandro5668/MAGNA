# Delta for qa-orchestrator

## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Supersede on Re-Sync

WHEN a new `ctx sync` triggers a QA run for a ticket that already has a run
in progress, the system MUST supersede the old run: discard its partial
artifacts and start fresh, never merge partial state across runs. The
ticket's persisted DB/URL confirmation MUST survive supersede and MUST NOT
be discarded with the other stage artifacts.
(Previously: superseded runs discarded all partial artifacts with no
exception.)

#### Scenario: Re-sync during an active run

- GIVEN a QA run for `PROJ-100` is in progress
- WHEN the user runs `ctx sync` again for `PROJ-100` before it finishes
- THEN the old run's partial artifacts are discarded and a new run starts
  from stage one

#### Scenario: Persisted DB choice survives supersede

- GIVEN `PROJ-100` has a persisted DB/URL confirmation from an earlier run
- WHEN a new run supersedes the in-progress one
- THEN the new run reuses the persisted DB/URL choice without re-asking
