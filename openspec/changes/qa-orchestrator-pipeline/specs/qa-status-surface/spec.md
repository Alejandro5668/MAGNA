# qa-status-surface Specification

## Purpose

TUI visibility for QA pipeline state: badge in the ticket list, completion
notifications, and on-demand evidence viewing — advisory only, never a gate.

## Requirements

### Requirement: QA Badge in Ticket List

`TicketPanel._row()` MUST render a QA status badge per ticket reflecting the
latest known state: none, in-progress, pass, fail, doubtful, or
manual-review.

#### Scenario: Badge reflects aggregator's terminal state

- GIVEN the aggregator wrote `manual_review` for a ticket
- WHEN the ticket list refreshes via `_fetch()`
- THEN that ticket's row shows the manual-review badge

### Requirement: Completion Notification

The system MUST call `notify()` when the QA pipeline reaches any terminal
state (pass, fail, doubtful, manual-review), independent of the
correction-cycle notifications.

#### Scenario: User is notified when QA finishes

- GIVEN a QA run reaches a terminal state while the TUI is open
- WHEN the aggregator writes that state
- THEN a notification summarizing the outcome appears in the TUI

### Requirement: Evidence Viewable on Demand

The system MUST let the user open a stage's or the aggregator's evidence
JSON/log through a parameterized `LogScreen` accepting a log path.

#### Scenario: User inspects evidence for a failed stage

- GIVEN the verify stage failed for a ticket
- WHEN the user opens that ticket's QA evidence in the TUI
- THEN `LogScreen` displays the verify stage's evidence file content

### Requirement: Advisory-Only Status

`qa_verified` MUST NOT gate ticket close, commit, or PR anywhere in this
system; it is informational only in this slice.

#### Scenario: Commit proceeds despite QA fail

- GIVEN a ticket's QA state is `fail`
- WHEN the user commits or closes that ticket
- THEN the action proceeds unblocked, with `qa_verified: false` recorded only as information
