# Exploration: qa-verification-protocol

## Current State

`build_context(modules: list[Module], project_path: Path | None = None) -> tuple[str, list[str]]`
(`aicli/services/builder.py:9`) assembles `session_context.md` fragments; team rule files from
`~/.mycontext/rules/*.md` are prepended first (lines 17-24) — confirmed accurate.

`_execute_task(task_desc, file=None, image=None, ticket_history=None, ticket_id=None, jira_data=None, suspend_fn=None)`
(`aicli/commands/task.py:108-116`) — `task_desc` and `jira_data` are both parameters. It calls
`build_context(relevant, project_path=path)` at `task.py:288`, passing the module list `relevant`,
**not** `task_desc`/`jira_data`. Any `es_bug` signal must be threaded as a new explicit argument —
`build_context` does not see task text today.

`fetch_issue` (`aicli/services/jira.py:78-107`) returns exactly
`{id, summary, description, priority, status, reporter, assignee, attachments}` — no
`issuetype`/`issueType` field. Any bug-classification heuristic must be text-based
(summary/description), not a Jira field.

`aicli/services/qa_protocol.py` does not exist — confirmed new file.

`~/.mycontext/` is the established out-of-repo storage root
(`aicli/db/__init__.py:11` `_db_path`, `aicli/commands/init.py:155` `rol_path`,
`builder.py:18/26/33`), so `~/.mycontext/projects/<project_id>/e2e/` is architecturally
consistent as a per-project Playwright regression suite location that never touches a client repo.

No pytest anywhere in the repo (no `pytest.ini`/`pyproject.toml`/`setup.cfg`, no CI workflow).
Two hand-rolled test styles coexist: `tests/test_commands.py` (custom `check()` smoke harness,
run via `py tests/test_commands.py`) and `tests/test_tickets.py` (stdlib `unittest`, run via
`py -m unittest tests/test_tickets.py -v`, `MYCONTEXT_HOME` env redirection for isolation).
Strict TDD / a single test command must not be assumed.

## Discrepancy Found (important — corrects prior assumption)

The prior assumption of "4 call sites of `build_context` (2 in `task.py`, 2 in `claude_cmd.py`)"
is inaccurate as a real-invocation count. There are exactly **3 real invocation sites, in 3 files**:

- `aicli/commands/task.py:288` (import at `:12`)
- `aicli/commands/claude_cmd.py:46` (import at `:9`)
- `aicli/tui/screens.py:414`, via local alias `_build_ctx` imported at `:397`, inside
  `_run_resume_tui` — a live production TUI code path (ticket reopen/resume flow), entirely
  omitted from the original assumption.

The "4" only reconciled by counting import-line + call-line pairs in `task.py` and
`claude_cmd.py` (2+2) while missing `screens.py`'s own import+call pair.

**Any change threading `es_bug` through `build_context`/`_execute_task` MUST also update
`aicli/tui/screens.py:397/414`**, or the TUI resume flow silently loses bug-classification
context that the CLI path gets.

`tests/test_commands.py:214/218` only asserts `callable(build_context)` — no real invocation,
so it won't break on a signature change but also won't catch a bad one.

## Style Conventions Confirmed (for a new `aicli/services/qa_protocol.py`)

Pure functions, no classes, snake_case, type hints on all public functions
(`str | None`, `dict`, `list[str]`, `-> tuple[...]`), Spanish docstrings/log messages/user-facing
strings, English identifiers. Heavy/optional deps (e.g. `httpx`) imported lazily inside the
function that needs them (`jira.py` pattern); core deps (`sqlmodel`) imported at module top
(`builder.py` pattern).

## Threading/Concurrency Risk Confirmed

`_execute_task` genuinely executes on a background thread in the TUI path:
`aicli/tui/screens.py:1554-1555` runs `loop.run_in_executor(pool, _dispatch_tui, "task", inputs, tui_console)`
with `concurrent.futures.ThreadPoolExecutor(max_workers=1)`, and `_dispatch_tui` calls
`_execute_task` at `screens.py:372`. Any new `es_bug` computation must stay a pure function of
its local arguments (`task_desc`, `jira_data`) — no shared mutable/global state, consistent with
existing patterns.

The reopened-ticket flow prefixes `task_desc` as `f"[TICKET REABIERTO {ticket_id}] {reason}"`
(`screens.py:521-522`) — the bug-classification heuristic must be validated against this text
shape too, not just raw free-text descriptions.

## No Prior Art

`knowledge/decisions.md` has no existing DEC entry for a QA/bug-verification protocol —
genuinely new scope, no conflicting prior decision to reconcile.

## Ready for Proposal

Yes, with one required correction carried forward: the proposal/design phase must scope
`aicli/tui/screens.py` (import `:397`, call `:414`) as a required change site alongside
`task.py` and `claude_cmd.py`, not just the 2 files implied by the original "4 call sites"
assumption.

---
Source: Engram `sdd/qa-verification-protocol/explore` (observation #178), materialized to
OpenSpec by the orchestrator — the explore sub-agent's toolset (Read/Grep/Glob/WebFetch/WebSearch/mem_save)
has no filesystem write access, per `sdd-explore` agent definition.
