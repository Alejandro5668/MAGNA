# qa-correction-cycle Specification

## Purpose

Bounded, audited self-correction: when verify or regression fails, at most
two scoped correction attempts run before the ticket is flagged for manual
review, each attempt notified and committed independently.

## Requirements

### Requirement: Bounded Correction Cycles

The system MUST attempt at most 2 correction cycles per QA run. After 2
failed attempts, the system MUST stop correcting and flag the ticket for
manual review — never blocked, never auto-reverted.

#### Scenario: Correction cap exhausted

- GIVEN 2 correction attempts have each failed re-verification
- WHEN the pipeline evaluates the result
- THEN the ticket is flagged for manual review and no third attempt runs
- AND the ticket is not blocked or reverted

### Requirement: File Scoping for Corrections

Each correction attempt MUST limit its edits to files the original fix
already touched and MUST NOT introduce edits to unrelated files.

#### Scenario: Correction stays within touched files

- GIVEN the original fix touched `foo.py` and `bar.py`
- WHEN a correction attempt runs
- THEN its diff only contains changes within `foo.py` and/or `bar.py`

### Requirement: Never Correct on Repro Failure

WHEN the repro stage produces `not_reproduced` (doubtful) or `blocked`
(attempted but environment prevented execution), the system MUST NOT start
any correction cycle. A `severe` security finding from the review stage
MUST NEVER open a correction cycle either.

#### Scenario: Doubtful ticket skips correction

- GIVEN repro could not reproduce the bug
- WHEN the pipeline proceeds
- THEN no correction attempt is launched and the ticket is marked doubtful

#### Scenario: Blocked ticket skips correction

- GIVEN repro was `blocked` by an unreachable DB or browser mid-attempt
- WHEN the pipeline proceeds
- THEN no correction attempt is launched

#### Scenario: Security finding never triggers correction

- GIVEN review reported a `severe` security finding
- WHEN the aggregator routes the ticket to `manual_review`
- THEN no correction cycle starts for that finding

### Requirement: Start and Terminal Notifications

The system MUST call `self.app.notify()` at the start of each correction
attempt and again once the pipeline reaches any terminal state.

#### Scenario: Notification fires before an unattended edit

- GIVEN a correction attempt is about to begin
- WHEN it starts
- THEN a notification naming the stage and attempt number (`n/2`) fires before any file edit

### Requirement: One Git Commit Per Attempt

Each correction attempt MUST produce exactly one git commit on the ticket's
branch, MUST NOT be squashed into the original fix commit, and MUST NOT be
auto-pushed.

#### Scenario: Single successful correction is auditable

- GIVEN one correction attempt fixes the failure and re-verification passes
- WHEN the developer runs `git log` on the ticket branch
- THEN exactly one new commit shaped `fix(qa-auto): corrección automática 1/2 — <motivo>` appears, unpushed
