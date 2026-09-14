# Delta for qa-status-surface

## ADDED Requirements

### Requirement: Review Findings in Evidence Digest

The evidence viewer MUST surface the review stage's `security` and
`quality` sections when present, and the badge vocabulary MUST remain
byte-identical to the existing set (none, in-progress, pass, fail,
doubtful, manual-review) — no new badge is introduced for the review stage
or for security findings.

#### Scenario: Evidence view shows review findings

- GIVEN a ticket's review stage wrote `security` and `quality` findings
- WHEN the user opens that ticket's QA evidence in the TUI
- THEN `LogScreen` displays both sections' content

#### Scenario: Security-triggered manual_review uses the existing badge

- GIVEN the aggregator set `manual_review` due to a severe security finding
- WHEN the ticket list refreshes
- THEN the row shows the existing manual-review badge, not a new one
