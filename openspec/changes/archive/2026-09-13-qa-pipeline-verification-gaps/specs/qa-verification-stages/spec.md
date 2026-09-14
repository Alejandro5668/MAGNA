# Delta for qa-verification-stages

## ADDED Requirements

### Requirement: Review Stage Contract

A single combined `review` stage MUST run after every `verify: pass` and
MUST read only the fix diff and touched files (never the whole repo). It
MUST produce one JSON evidence file with two structurally separate
sections, `security` and `quality`. Security findings MUST be classified
only against a fixed, hard-coded allowlist of blocking categories: SQL
injection, command injection, path traversal, unsafe deserialization,
credential/secret exposure, sensitive data exposure, authentication bypass,
authorization bypass, XSS, and SSRF. Only a
finding matching one of these categories MAY be marked `severe`; every other
security observation and every quality finding MUST be advisory-only,
visible in `evidence.log`, and MUST NEVER change the verdict.

#### Scenario: Review runs only after verify passes

- GIVEN verify has just produced `pass`
- WHEN the pipeline proceeds
- THEN the review stage starts and reads the fix diff plus touched files

#### Scenario: Non-allowlisted finding stays advisory

- GIVEN review reports a code-duplication finding and a security observation
  outside the fixed allowlist
- WHEN the review stage finishes
- THEN both are recorded in `evidence.log` as advisory and neither is marked
  `severe`

#### Scenario: Allowlisted finding is marked severe

- GIVEN review detects a SQL injection pattern introduced by the fix
- WHEN it writes its evidence
- THEN the `security` section marks that finding `severe`

## MODIFIED Requirements

### Requirement: Repro Stage Isolation

The repro stage MUST receive the original bug report/repro steps plus real
environment context — the DB access rule and the ticket's confirmed DB/URL
— and MUST NOT receive the fix diff, commit message, or any knowledge that a
fix was made. It MUST produce one of: `reproduced`, `not_reproduced`
(doubtful), `blocked` (attempted but environment prevented execution). If
the ticket's DB/URL confirmation is missing or unavailable when repro is
about to run, the stage MUST NOT execute and MUST NOT silently drop to
`manual_review`; the pipeline MUST pause as `awaiting_input` via
`_finalize_awaiting_input`/`resume_qa` until the user supplies it.
(Previously: repro received only the bug report/repro steps with no DB or
browser context, and could only produce `reproduced` or `not_reproduced`.)

#### Scenario: Repro cannot see the fix

- GIVEN a repro stage session starts for a ticket
- WHEN its prompt/context is assembled
- THEN it contains no reference to the fix diff or fix commit, even though
  it includes the confirmed DB/URL and access rule

#### Scenario: Bug not reproducible marks doubtful

- GIVEN the repro stage attempted reproduction with real DB/browser context
  and could not trigger the reported bug
- WHEN it finishes
- THEN it writes `not_reproduced` evidence and the pipeline enters the
  doubtful state, never correction

#### Scenario: Missing DB/URL context pauses instead of dropping to manual_review

- GIVEN a ticket's confirmed DB/URL is missing when repro is about to run
- WHEN the pipeline reaches the repro stage
- THEN it pauses as `awaiting_input`, records no repro verdict, and resumes
  repro only after `resume_qa` supplies the DB/URL

#### Scenario: Environment failure attempted but blocked

- GIVEN repro has a confirmed DB/URL and attempts reproduction
- WHEN the DB or browser becomes unreachable mid-attempt
- THEN repro writes `blocked` evidence, distinct from `not_reproduced`,
  recording that an attempt occurred

### Requirement: Aggregator Sole Ownership

The aggregator MUST be pure Python (no LLM call) and MUST be the only
component that writes the ticket's final `qa_verified` state, computed from
the other stages' evidence, always producing a terminal state — including on
timeout. The aggregator MUST consume the review stage's `security`
section: a `severe` finding MUST set the final state to `manual_review`
with `reason: "security_finding_severe"`. The review stage's `quality`
section MUST NEVER influence the final state.
(Previously: the aggregator had no review-stage input; only repro, verify,
and regression evidence fed the truth table.)

#### Scenario: No stage besides aggregator sets qa_verified

- GIVEN repro, verify, and regression have each written their own evidence
  file
- WHEN the pipeline concludes
- THEN only the aggregator's evidence file contains the final `qa_verified`
  value

#### Scenario: Malformed stage JSON never counts as a pass

- GIVEN a stage's evidence file contains trailing non-JSON noise or is
  unparseable after `raw_decode` tolerance
- WHEN the aggregator reads it
- THEN it treats that stage as failed, never as passed

#### Scenario: Severe security finding forces manual_review

- GIVEN review wrote a `severe` finding in its `security` section
- WHEN the aggregator computes the final state
- THEN it writes `manual_review` with `reason: "security_finding_severe"`,
  regardless of verify/regression results

#### Scenario: Quality findings never move the verdict

- GIVEN review wrote only `quality` findings with no `severe` security entry
- WHEN the aggregator computes the final state
- THEN the verdict is unaffected by those quality findings
