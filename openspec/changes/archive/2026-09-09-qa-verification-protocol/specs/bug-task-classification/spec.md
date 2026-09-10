# Delta for bug-task-classification

## ADDED Requirements

### Requirement: Pure Bug-Task Heuristic
The system MUST expose `is_bug_task(desc: str, jira_data: dict | None) -> bool` in `aicli/services/qa_protocol.py`, evaluating a Spanish keyword heuristic over the task description and, when present, the Jira issue's summary/description. `is_bug_task` MUST be a pure function of its arguments — it MUST NOT read or write any module-level mutable state, since callers may run it from a background worker thread.

#### Scenario: Keyword match on description
- GIVEN a task description containing a bug-indicating Spanish keyword
- WHEN `is_bug_task` is called with that description and no Jira data
- THEN it returns `True`

#### Scenario: Keyword match on Jira summary only
- GIVEN a Jira issue whose summary contains a bug keyword while the free-text task description does not
- WHEN `is_bug_task` is called with that description and the Jira data
- THEN it returns `True`

#### Scenario: No AI call, no issuetype field
- GIVEN any input combination
- WHEN `is_bug_task` evaluates it
- THEN the evaluation uses only keyword matching over provided text fields, makes no AI/network call, and does not read a Jira `issuetype` field

#### Scenario: Repeated calls are independent
- GIVEN two consecutive calls to `is_bug_task` with different arguments, invoked from concurrent or sequential threads
- WHEN both calls complete
- THEN each call's result depends only on its own arguments, with no leakage or shared state between calls

### Requirement: Reopen Marker Is a Positive Signal
`is_bug_task` MUST return `True` whenever the task description carries the `[TICKET REABIERTO` prefix, regardless of whether the remaining text matches any keyword.

#### Scenario: Reopen prefix alone triggers classification
- GIVEN a task description equal to `"[TICKET REABIERTO ABC-123] no carga el listado"`
- WHEN `is_bug_task` is called with that description
- THEN it returns `True`

### Requirement: Recall-Biased Keyword Set
The keyword heuristic SHOULD be biased toward recall over precision: it MUST accept a broader keyword set even where that risks classifying a non-bug task as a bug, on the basis that a false positive costs extra protocol overhead while a false negative skips verification entirely.

#### Scenario: Ambiguous phrasing favors bug classification
- GIVEN a task description phrased ambiguously but containing a broad bug-adjacent keyword
- WHEN `is_bug_task` evaluates it
- THEN it returns `True` rather than requiring an unambiguous bug statement

### Requirement: Conditional QA Protocol Injection in build_context
`build_context` (`aicli/services/builder.py`) MUST accept a keyword-defaulted `es_bug: bool = False` parameter. WHEN `es_bug` is `True`, `build_context` MUST prepend `QA_PROTOCOL` as the first fragment of the assembled context, ahead of the team-rule fragments. WHEN `es_bug` is `False` or omitted, `build_context` MUST NOT include `QA_PROTOCOL` and MUST produce output identical to today's behavior.

#### Scenario: Bug session receives protocol first
- GIVEN `build_context` is called with `es_bug=True`
- WHEN the context string is assembled
- THEN `QA_PROTOCOL` is the first fragment, appearing before the team-rule fragments

#### Scenario: Default call is unaffected
- GIVEN `build_context` is called without specifying `es_bug` (or with `es_bug=False`)
- WHEN the context string is assembled
- THEN no `QA_PROTOCOL` fragment appears anywhere in the output

### Requirement: Single Classification Call Site
`_execute_task` (`aicli/commands/task.py`) MUST be the only call site that computes `es_bug` (via `is_bug_task` on its own `task_desc`/`jira_data` locals) and passes it into `build_context`. All other existing `build_context` call sites MUST remain unchanged and continue to omit `es_bug`, relying on its default.

#### Scenario: ctx task classifies and threads es_bug
- GIVEN a user runs `ctx task` with a bug-shaped description
- WHEN `_execute_task` calls `build_context`
- THEN `es_bug` is computed from that call's `task_desc`/`jira_data` and passed explicitly

#### Scenario: CLI and TUI resume inherit classification via the shared call site
- GIVEN a ticket is resumed from either the CLI resume flow or the TUI resume flow
- WHEN each flow reaches `build_context` through `_execute_task`
- THEN both receive the same `es_bug` computation without either flow needing its own classification logic

#### Scenario: Free-question paths remain byte-identical
- GIVEN a user runs `ctx claude` (CLI) or opens the free-question TUI flow, asking a question that describes a bug
- WHEN the session context is assembled
- THEN `build_context` is called exactly as it was before this change (no `es_bug` argument, default `False` applies), and the resulting `session_context.md` is byte-identical to the pre-change output for the same modules and inputs

### Requirement: Minimal Real-Argument Test Coverage
The change MUST include tests that exercise `build_context` with real arguments for both `es_bug=True` and `es_bug=False`, and tests that exercise `is_bug_task` with real arguments, using the project's existing hand-rolled test styles. No pytest dependency MUST be introduced.

#### Scenario: build_context test coverage
- GIVEN the test suite is run
- WHEN `build_context` is invoked with `es_bug=True` and separately with `es_bug=False`
- THEN a test asserts the presence and ordering of `QA_PROTOCOL` in the `True` case and its absence in the `False` case

#### Scenario: is_bug_task test coverage
- GIVEN the test suite is run
- WHEN `is_bug_task` is invoked with representative bug and non-bug inputs, including the `[TICKET REABIERTO` case
- THEN a test asserts the expected boolean result for each case
