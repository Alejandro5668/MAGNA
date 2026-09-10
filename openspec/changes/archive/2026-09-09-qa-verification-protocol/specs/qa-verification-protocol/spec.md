# Delta for qa-verification-protocol

## ADDED Requirements

### Requirement: Test Plan Before Verification
`QA_PROTOCOL` MUST require Claude to write an explicit test plan — covering the happy path plus the edge cases, roles, and data variants it identifies for that specific bug — before running any verification step, and to follow it point by point.

#### Scenario: Plan precedes execution
- GIVEN a bug-shaped session with `QA_PROTOCOL` loaded
- WHEN Claude begins verification
- THEN a written test plan exists before any reproduction or browser action is taken

#### Scenario: Plan covers identified variants
- GIVEN a bug that affects multiple user roles or data shapes
- WHEN the test plan is written
- THEN it enumerates the role- and data-variant cases identified, not only the happy path

### Requirement: Independent Reproduction
The protocol MUST require Claude to reproduce the reported bug from scratch rather than trusting the ticket's own stated diagnosis or root cause.

#### Scenario: Reproduction attempted before fixing
- GIVEN a ticket that states a root cause
- WHEN Claude begins work
- THEN Claude reproduces the failure independently before applying or trusting any fix

### Requirement: Real Browser Verification With Deep Inspection
The protocol MUST require verification in a real browser session (via the already-installed `claude-in-chrome` capability) and MUST require inspection of browser console and network activity, not only the visual page state. When the bug involves a data write, the protocol MUST require verifying real database state.

#### Scenario: Console and network checked
- GIVEN a fix applied to a UI bug
- WHEN Claude verifies the fix in the browser
- THEN Claude inspects console errors and network requests/responses, not only what renders visually

#### Scenario: DB state checked for data-write bugs
- GIVEN a bug where the fix writes or modifies persisted data
- WHEN Claude verifies the fix
- THEN Claude confirms the real database state reflects the expected outcome

### Requirement: Production Read-Only By Default
The protocol MUST treat any production environment as read-only during verification. Claude MUST NOT perform write actions in production unless the user has explicitly authorized writes for that specific case.

#### Scenario: Default read-only
- GIVEN verification is happening against production
- WHEN no explicit write authorization was given by the user
- THEN Claude performs only read/observation actions in production

#### Scenario: Explicit authorization granted
- GIVEN the user has explicitly authorized a production write for this specific case
- WHEN Claude verifies the fix
- THEN Claude may perform that authorized write and no other

### Requirement: Pause on Missing Data
When data required for verification is unavailable (e.g., a missing client DB backup), the protocol MUST require Claude to pause and explicitly ask the user rather than guessing or proceeding with assumed data.

#### Scenario: Required data absent
- GIVEN verification requires data that is not accessible
- WHEN Claude detects the gap
- THEN Claude stops and asks the user explicitly instead of fabricating or assuming the missing data

### Requirement: Bounded Retry With Escalation
On a failed verification, the protocol MUST require Claude to retry the fix using the new evidence gathered from the failure, up to a cap of 3 attempts. After the cap is reached, Claude MUST escalate to the user with a stated hypothesis and the evidence gathered, instead of continuing silently or declaring success.

#### Scenario: Retry uses new evidence
- GIVEN a verification attempt fails
- WHEN Claude retries
- THEN the retry incorporates evidence gathered from the failed attempt, not a repeat of the same action

#### Scenario: Escalation after cap
- GIVEN 3 verification attempts have failed
- WHEN a 4th attempt would be needed
- THEN Claude escalates to the user with a hypothesis and the evidence collected, and does not attempt a 4th fix silently

### Requirement: No Resolution Without Verification
The protocol MUST prohibit declaring a case resolved unless verification per this protocol has been completed and passed.

#### Scenario: Unverified fix not declared done
- GIVEN a fix has been applied but verification has not completed
- WHEN Claude reports session status
- THEN the case is not reported as resolved/verified
