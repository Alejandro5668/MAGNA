# Delta for qa-outcome-tracking

## ADDED Requirements

### Requirement: Session-Produced Verification Artifact
A bug-shaped Claude Code session that completes the QA protocol MUST leave behind a discoverable, session-produced artifact expressing at least `verified: bool` and `attempts: int` for that verification round. The exact file location and format are an implementation decision (deferred to design); this requirement constrains only the observable contract: the artifact MUST be readable by a subsequent, separate process (`ctx sync`) without requiring the originating session to still be running.

#### Scenario: Verification result is discoverable after session ends
- GIVEN a bug session completed its QA protocol and the session process has since exited
- WHEN a later process looks for that session's verification result
- THEN it can locate and read a `verified: bool` and `attempts: int` outcome for that round

### Requirement: ctx sync Passes Through Verification Ground Truth
`ctx sync` (`aicli/commands/sync.py`) MUST attempt to read the session's verification artifact for the ticket round being saved, before its call to `save_round`, and MUST pass the resulting `qa_verified` value into that call.

#### Scenario: Verified result flows into save_round
- GIVEN a session left a verification artifact with `verified: True`
- WHEN `ctx sync` saves that round
- THEN `save_round` is called with `qa_verified=True`

#### Scenario: Failed verification flows into save_round
- GIVEN a session left a verification artifact with `verified: False`
- WHEN `ctx sync` saves that round
- THEN `save_round` is called with `qa_verified=False`

### Requirement: save_round Stores Ground-Truth QA Outcome
`save_round` (`aicli/services/tickets.py`) MUST accept a keyword-defaulted `qa_verified: bool | None = None` parameter and MUST store it in the persisted `ronda` dict alongside the existing `mensaje_jira`, `motivo_reapertura`, and `memoria` fields.

#### Scenario: qa_verified persisted with the round
- GIVEN `save_round` is called with `qa_verified=True`
- WHEN the round is written to the ticket's stored rounds
- THEN the persisted `ronda` entry includes `qa_verified: True` alongside its other fields

#### Scenario: Existing callers remain valid
- GIVEN a caller invokes `save_round` without passing `qa_verified`
- WHEN the round is saved
- THEN the call succeeds and the persisted round has `qa_verified: None`

### Requirement: Missing or Unreadable Result Defaults to Unknown, Never False
WHEN no verification artifact is found, or it cannot be read/parsed, `ctx sync` MUST treat the outcome as unknown (`None`) and MUST NOT default it to `False`.

#### Scenario: No artifact found
- GIVEN a session ended (crash or manual close) without producing a verification artifact
- WHEN `ctx sync` saves that round
- THEN `save_round` is called with `qa_verified=None`, not `qa_verified=False`

#### Scenario: Artifact present but unparsable
- GIVEN a verification artifact exists but is corrupted or malformed
- WHEN `ctx sync` attempts to read it
- THEN `ctx sync` treats the result as unknown and calls `save_round` with `qa_verified=None`

### Requirement: qa_verified Is Never AI-Inferred
`generate_case_summary` (`aicli/services/indexer.py`) MUST NOT be used to infer or set `qa_verified`. `qa_verified` MUST only ever be sourced from the session's own verification artifact, since `generate_case_summary` has visibility only into the git diff and task text and no visibility into browser-verification evidence.

#### Scenario: Case summary generation does not touch qa_verified
- GIVEN `generate_case_summary` runs for a completed round
- WHEN it produces its summary text
- THEN it does not set, guess, or influence the `qa_verified` value for that round
