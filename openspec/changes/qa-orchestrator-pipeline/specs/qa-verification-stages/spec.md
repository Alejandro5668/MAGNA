# qa-verification-stages Specification

## Purpose

Role contracts for the four independent QA stages — repro, verify,
regression, aggregator — including input isolation, evidence schema, and the
pass/fail/doubtful states each stage may produce.

## Requirements

### Requirement: Repro Stage Isolation

The repro stage MUST receive only the original bug report/repro steps and
MUST NOT receive the fix diff, commit message, or any knowledge that a fix
was made. It MUST produce one of: `reproduced`, `not_reproduced` (doubtful).

#### Scenario: Repro cannot see the fix

- GIVEN a repro stage session starts for a ticket
- WHEN its prompt/context is assembled
- THEN it contains no reference to the fix diff or fix commit

#### Scenario: Bug not reproducible marks doubtful

- GIVEN the repro stage cannot trigger the reported bug
- WHEN it finishes
- THEN it writes `not_reproduced` evidence and the pipeline enters the doubtful state, never correction

### Requirement: Verify Stage Contract

The verify stage MUST use a real browser and read-only database access only,
MUST NOT perform any production write, and MUST produce `pass` or `fail`
evidence against the reproduced bug.

#### Scenario: Verify passes after a real fix

- GIVEN repro reproduced the bug and a fix was applied
- WHEN verify re-attempts the same steps in-browser
- THEN it records `pass` only if the bug no longer occurs

### Requirement: Regression Stage Contract

The regression stage MUST run in a separate repository via `npx playwright
test` for re-runs (no LLM tokens spent), using Playwright MCP only to
author/update tests, and MUST produce `pass` or `fail` evidence.

#### Scenario: Regression re-run spends no tokens

- GIVEN an existing regression suite
- WHEN the regression stage re-runs it
- THEN it executes via `npx playwright test` without invoking an LLM session

### Requirement: Aggregator Sole Ownership

The aggregator MUST be pure Python (no LLM call) and MUST be the only
component that writes the ticket's final `qa_verified` state, computed from
the other stages' evidence, always producing a terminal state — including on
timeout.

#### Scenario: No stage besides aggregator sets qa_verified

- GIVEN repro, verify, and regression have each written their own evidence file
- WHEN the pipeline concludes
- THEN only the aggregator's evidence file contains the final `qa_verified` value

#### Scenario: Malformed stage JSON never counts as a pass

- GIVEN a stage's evidence file contains trailing non-JSON noise or is unparseable after `raw_decode` tolerance
- WHEN the aggregator reads it
- THEN it treats that stage as failed, never as passed
