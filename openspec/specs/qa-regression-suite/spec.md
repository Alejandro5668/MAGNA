# Capability: qa-regression-suite

Per-project Playwright regression suite under `~/.mycontext/projects/<project_id>/e2e/` — generated/updated after a verified fix, run before trusting a new verification in a module that already has tests, always outside the client repo, Playwright autonomously installed with browsers.

## ADDED Requirements

### Requirement: Per-Project Regression Suite Location
The protocol MUST require any Playwright regression suite generated for a verified fix to live under `~/.mycontext/projects/<project_id>/e2e/` as a separate, standalone Node project with its own `package.json`, isolated from any client repository.

#### Scenario: Suite created outside client repo
- GIVEN a bug fix is verified in a project with `project_id` `P`
- WHEN the regression test is generated
- THEN the test files and `package.json` are written under `~/.mycontext/projects/P/e2e/`, not inside the client repo's tracked tree

### Requirement: Suite Generated or Updated After Verified Fix
The protocol MUST require Claude to generate a new Playwright test, or update an existing one, in the per-project `e2e/` suite after a fix has passed verification for that case.

#### Scenario: New test added after verification
- GIVEN a fix has just passed browser verification
- WHEN the session concludes its QA steps
- THEN a Playwright test covering that fix exists or is updated in the project's `e2e/` suite

### Requirement: Existing Suite Runs Before Trusting New Verification
When the affected module already has tests in the project's `e2e/` suite, the protocol MUST require Claude to run that existing suite before trusting a new verification result for that module.

#### Scenario: Regression check precedes new verification trust
- GIVEN the affected module has prior tests in `e2e/`
- WHEN Claude verifies a new fix in that module
- THEN the existing suite is run first, and its result is considered before the fix is declared verified

### Requirement: Never Modify the Client Repository for Testing Tooling
The protocol MUST prohibit writing, installing, or committing any testing artifact, dependency, or tooling (Playwright, `package.json`, `node_modules`, or any Node project file) inside the client repository, under any circumstance.

#### Scenario: No test tooling leaks into client repo
- GIVEN a verified fix in a client project's git-tracked tree
- WHEN the regression suite is generated, updated, or run
- THEN no `package.json`, `node_modules`, or other Playwright/Node artifact appears anywhere under the client project's own git-tracked tree

### Requirement: Autonomous Playwright Setup
When Playwright or its browsers are not yet installed in the per-project `e2e/` folder, the protocol MUST direct Claude to install them there automatically, without asking the user for confirmation.

#### Scenario: First run installs Playwright
- GIVEN the project's `e2e/` folder has no Playwright installation yet
- WHEN Claude needs to run or generate a regression test
- THEN Claude installs Playwright and its browsers inside that `e2e/` folder without prompting the user first
