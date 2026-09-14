# Delta for qa-correction-cycle

## MODIFIED Requirements

### Requirement: Never Correct on Repro Failure

WHEN the repro stage produces `not_reproduced` (doubtful) or `blocked`
(attempted but environment prevented execution), the system MUST NOT start
any correction cycle. A `severe` security finding from the review stage
MUST NEVER open a correction cycle either.
(Previously: only `not_reproduced` skipped correction; `blocked` did not
exist and review-stage findings were not a factor.)

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
