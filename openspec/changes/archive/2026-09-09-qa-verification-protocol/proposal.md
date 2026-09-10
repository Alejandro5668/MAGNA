# Proposal: QA verification protocol for bug-shaped tasks

## Intent

`ctx task` opens one Claude Code session per case (Jira → fix → done). Nothing in that session
instructs Claude to actually reproduce the bug and verify the fix in a real browser before
declaring the case resolved. Two costs follow: tickets get reopened because a fix was declared
done without exhaustive verification, and an already-fixed bug silently regresses when a later,
unrelated change lands.

Today `build_context` (`aicli/services/builder.py:9`) assembles `session_context.md` from modules,
team rules, `rol.md` and `PROYECTO.md` — it never sees the task text and carries no verification
policy. This change injects a fixed QA protocol as a top-priority context fragment, automatically,
only for tasks classified as bug-shaped.

Success looks like: a bug session that ends with a reproduction, a browser-verified fix following
an inspectable test plan, a Playwright regression test stored outside the client repo, and a
truthful `qa_verified` record — with no new command, no new UI, and no new AICLI dependency. The
user's target is to bring reopened tickets under 10%; `qa_verified` is what turns that target from
an intention into something measurable against real ticket history.

## Scope

### In Scope

- New `aicli/services/qa_protocol.py` exposing `QA_PROTOCOL: str` (fixed Spanish instruction block)
  and `is_bug_task(desc: str, jira_data: dict | None) -> bool` (keyword heuristic, no AI call).
- `build_context` gains `es_bug: bool = False` (`aicli/services/builder.py:9`); when `True`,
  `QA_PROTOCOL` is prepended as the first fragment, ahead of the team-rule fragments currently
  built at `builder.py:17-24`.
- `_execute_task` (`aicli/commands/task.py:108-116`) computes
  `es_bug = is_bug_task(task_desc, jira_data)` from its own locals and threads it into
  `build_context` at `task.py:288`.
- `QA_PROTOCOL` text encodes the verification rules and the regression-suite rules
  (`~/.mycontext/projects/<project_id>/e2e/`, standalone Node project, autonomous Playwright install
  in that folder only, never inside a client repo).
- `QA_PROTOCOL` requires Claude to write an explicit test plan (happy path + the edge
  cases/roles/data variants it identifies for that specific bug) before running verification, and
  to follow it point by point. This turns "exhaustive" from a self-assessed adjective into an
  artifact the user can read and judge — it does not change what gets tested, it makes the scope
  of testing inspectable.
- Ground-truth QA outcome measurement: the QA session leaves a verification result (verified: bool,
  attempts: int — exact file/format decided in design) that `ctx sync` (`aicli/commands/sync.py:390`)
  reads and passes to `save_round` (`aicli/services/tickets.py:136`, new `qa_verified: bool | None = None`
  param, stored in the `ronda` dict). This is NOT inferred by the existing `generate_case_summary`
  AI call (`aicli/services/indexer.py:240`) — that call only sees the git diff and task text, never
  the browser-verification evidence from the Claude Code session, so it cannot know whether
  verification actually happened. Ground truth must come from the session itself. This lets reopen
  rate be computed later, with vs. without verification, directly from existing ticket history —
  no dashboard, no new storage system.
- New DEC entry in `knowledge/decisions.md`.

### Out of Scope

- Wiring up `claude-in-chrome`. It is an already-installed global Claude Code capability; the
  protocol text references it, AICLI does not integrate it.
- Any AICLI code that installs, runs, or parses Playwright. Installation and execution happen inside
  the Claude Code session, driven by `QA_PROTOCOL` text — not by new Python.
- New CLI command, new TUI screen, new flag. Activation is entirely automatic via `es_bug`.
- AI-based bug classification, or reading a Jira `issuetype` field — `fetch_issue`
  (`aicli/services/jira.py:78-107`) does not return one.
- Free-question mode (`ctx claude` and its TUI twin). Both stay at the `es_bug=False` default.
- A pytest migration. See Risks for the minimal test we do propose.
- Any dashboard, report, or analytics view over `qa_verified` — only the raw field is in scope. Reading
  the reopen rate back out is a manual query over `~/.mycontext/tickets/*.json` for now.
- Inferring `qa_verified` from the diff/AI case summary — rejected as unreliable, see In Scope.

## Capabilities

### New Capabilities

- `qa-verification-protocol`: the fixed verification contract injected into bug sessions —
  write a test plan (happy path + identified edge cases/roles/data variants) before executing,
  reproduce before trusting the ticket, verify in a real browser, inspect console/network, verify
  real DB state on writes, read-only in production unless explicitly authorized, pause and ask when
  data is missing, retry with new evidence up to 3 attempts then escalate, never declare resolved
  without verification.
- `qa-regression-suite`: per-project Playwright suite under `~/.mycontext/projects/<id>/e2e/` —
  generated/updated after a verified fix, run before trusting a new verification in a module that
  already has tests, always outside the client repo.
- `bug-task-classification`: `is_bug_task` heuristic over task description and Jira
  summary/description.
- `qa-outcome-tracking`: ground-truth `qa_verified` recorded per ticket round, sourced from the
  session's own verification result rather than inferred — the measurement substrate for the
  reopened-rate goal driving this whole change.

### Modified Capabilities

- None (`openspec/specs/` does not exist yet).

## Approach

**Fixed text, not generated.** `QA_PROTOCOL` is a module-level constant, not an AI-produced brief.
It is a policy that must be identical in every bug session; generating it would add cost, latency
and drift for no benefit. This also keeps the change free of new dependencies, consistent with
`openspec/config.yaml` (`No new AICLI (Python) dependencies`).

**Highest-priority position.** `builder.py:17` already documents the ordering intent — team rules
come first "so Claude treats them as highest-priority constraints". A verification protocol that
Claude may deprioritize is worthless, so `QA_PROTOCOL` is prepended ahead of them.

**One call site, not three — correction to the exploration.** The exploration (and the scope brief
derived from it) recorded `aicli/tui/screens.py:414` as living inside `_run_resume_tui` and therefore
requiring its own `es_bug` threading. Direct verification contradicts this:

- `screens.py:414` is inside the `elif command == "claude":` branch of `_dispatch_tui`
  (branch opens at `screens.py:392`), and its result feeds
  `_launch(context, task=inputs["duda"], question_mode=True)` at `screens.py:418`. It is the TUI
  twin of `claude_cmd.py:46`, i.e. free-question mode.
- `_run_resume_tui` starts at `screens.py:421` — *after* that call — and reaches Claude through
  `task_mod._execute_task(...)` at `screens.py:521`. The CLI resume path `_run_resume`
  (`screens.py:263`) likewise calls `_execute_task` at `screens.py:324`.

Both reopen flows therefore already funnel through `_execute_task` → `build_context`
(`task.py:288`). Computing `es_bug` once inside `_execute_task` covers `ctx task`, CLI resume and
TUI resume together. `screens.py:414` and `claude_cmd.py:46` are free-question paths where bug
classification does not apply and stay at the default — both are listed as confirmed unchanged
rather than silently omitted.

**Reopened tickets classify as bugs by construction.** Both resume paths build `task_desc` as
`f"[TICKET REABIERTO {ticket_id}] {reason}"` (`screens.py:325`, `screens.py:522`), where `reason` is
prefilled from the latest Jira comment (`screens.py:314`, `screens.py:511`) or typed by hand. Since a
reopen is almost always a failed fix, `is_bug_task` treats the `[TICKET REABIERTO` marker as a
positive signal on its own, rather than depending on whether the QA comment happens to contain a
keyword. See Proposal question round.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `aicli/services/qa_protocol.py` | New | `QA_PROTOCOL` constant + `is_bug_task()`; pure functions, no new imports |
| `aicli/services/builder.py:9` | Modified | New `es_bug: bool = False` param; prepend `QA_PROTOCOL` ahead of `builder.py:17-24` |
| `aicli/commands/task.py:288` | Modified | Compute `es_bug` from local `task_desc`/`jira_data` (`task.py:108-116`), pass into `build_context` |
| `aicli/tui/screens.py:324` | Confirmed unchanged | CLI resume reaches `build_context` via `_execute_task`; covered by `task.py:288` |
| `aicli/tui/screens.py:521` | Confirmed unchanged | TUI resume reaches `build_context` via `_execute_task`; covered by `task.py:288` |
| `aicli/tui/screens.py:414` | Confirmed unchanged | Free-question TUI path (`question_mode=True`, `screens.py:418`); stays `es_bug=False` |
| `aicli/commands/claude_cmd.py:46` | Confirmed unchanged | Free-question CLI path; stays `es_bug=False` |
| `tests/test_commands.py:214/218` | Modified | Currently only `callable(build_context)`; add real-argument coverage (see Risks) |
| `aicli/services/tickets.py:136` | Modified | `save_round` gains `qa_verified: bool \| None = None`, stored in the `ronda` dict |
| `aicli/commands/sync.py:390` | Modified | Reads the session's ground-truth QA result (if present) and passes `qa_verified` into `save_round` |
| `knowledge/decisions.md` | Modified | New DEC entry for the QA protocol and the out-of-repo e2e location |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Keyword heuristic misses a bug phrased without keywords (false negative — session runs with no QA protocol) | Med | Broad Spanish keyword set over description *and* Jira summary/description; `[TICKET REABIERTO` treated as a positive signal; failure mode is today's behavior, not a regression |
| Heuristic fires on a feature task (false positive — protocol overhead on non-bug work) | Med | Protocol instructs verification, not blocking; cost is extra context tokens and browser checks. Prefer recall over precision |
| Claude installs Playwright inside the client repo despite the protocol | Low | Explicit hard rule in `QA_PROTOCOL`: absolute path under `~/.mycontext/projects/<id>/e2e/`, never the client repo; reinforced by the existing `openspec/config.yaml` apply guideline |
| Production write during verification | Low | Protocol makes production testing read-only unless the user explicitly authorizes writes for that specific case |
| `QA_PROTOCOL` inflates `session_context.md` on every bug session | Med | Fixed block, injected only when `es_bug` is true; keep the text tight and review its size during spec |
| Signature change to `build_context` breaks an unnoticed caller | Low | New param is keyword-defaulted (`es_bug: bool = False`), so all existing calls stay valid; all 3 real call sites verified |
| No test exercises `build_context` with real arguments — `tests/test_commands.py:214/218` only asserts `callable(...)` | High | Spec/tasks phases add minimal real-argument coverage for `build_context(..., es_bug=True)` and `is_bug_task(...)`. Style choice deferred to spec: `tests/test_tickets.py` (stdlib `unittest`, `MYCONTEXT_HOME` redirection) is the better fit for `build_context` because it touches `~/.mycontext`; `is_bug_task` is pure and fits either harness. No pytest, no single test command — `openspec/config.yaml` sets `test_command: ""` |
| Shared state in `es_bug` computation corrupts a concurrent TUI run | Low | `_execute_task` runs on a background `ThreadPoolExecutor(max_workers=1)` thread (`screens.py:1554-1555` → `_dispatch_tui` → `screens.py:372`); `is_bug_task` is required to be a pure function of its arguments, no module-level mutable state |
| Escalation cap of 3 attempts hides a genuinely hard bug | Low | Protocol requires escalating with hypothesis + gathered evidence, not silent failure |
| Claude Code session ends (crash, user closes terminal) before writing the verification result — `qa_verified` would be silently wrong if defaulted to `False` | Med | `qa_verified` defaults to `None` (unknown) when no result is found, never `False`; `sync.py` treats missing as unknown, not as "failed" |
| `qa_verified` measurement becomes unused data nobody reads | Low | Deliberately out of scope to build a dashboard now; the field only needs to exist and be truthful — reading it back is a manual query when the user wants to check progress |

## Rollback Plan

Revert the commit. `qa_protocol.py` is a new isolated module with no importers after revert; the
`es_bug` parameter is keyword-defaulted, so reverted `build_context` callers stay valid without
coordination. Nothing is written to the client repo, and no database schema or stored file format
changes — the only persistent residue is whatever Playwright suite Claude created under
`~/.mycontext/projects/<id>/e2e/`, which becomes an inert unused folder and can be deleted manually.
No migration, no data loss path.

## Dependencies

- No new Python packages. `qa_protocol.py` uses stdlib only.
- Playwright and its browsers are installed by Claude Code at session time, inside
  `~/.mycontext/projects/<id>/e2e/` only. AICLI neither requires nor orchestrates them.
- `claude-in-chrome` must already be available in the user's Claude Code install (assumed present;
  out of scope to verify or install).

## Proposal question round

Execution mode is `auto` and the change was scoped with the user across prior turns, so the
following are recorded as assumptions rather than blocking questions. They should be corrected
before spec if any is wrong:

1. **Reopen marker as a bug signal.** Assumed: `[TICKET REABIERTO` in `task_desc` makes
   `is_bug_task` return `True` regardless of the rest of the text. Alternative: rely only on
   keywords in the reason/Jira text, accepting that a reopen phrased neutrally skips the protocol.
2. **Free-question mode stays excluded.** Assumed: `ctx claude` and its TUI twin never get the QA
   protocol, even when the question is clearly about a bug. Alternative: classify `duda` text too.
3. **Recall over precision.** Assumed: a false positive (protocol on a feature task) is cheaper than
   a false negative (unverified bug fix), so the keyword set is deliberately broad.
4. **Regression suite is per-project, not per-module.** Assumed: one `e2e/` Node project per
   `project_id`, with tests organized inside it by module.
5. **Minimal test coverage is in scope for this change.** Assumed: spec/tasks add real-argument
   tests for `build_context(es_bug=True)` and `is_bug_task(...)` in the existing hand-rolled style,
   without introducing pytest.

## Success Criteria

- [ ] A bug-shaped `ctx task` session receives `QA_PROTOCOL` as the first fragment of
      `session_context.md`, ahead of team rules.
- [ ] A reopened ticket (both CLI and TUI resume paths) is classified as a bug and receives the
      protocol.
- [ ] `ctx claude` and the TUI free-question path produce byte-identical context to today.
- [ ] `is_bug_task` returns `True` for `"[TICKET REABIERTO ABC-123] no carga el listado"` and for a
      Jira issue whose summary contains a bug keyword while the free-text description does not.
- [ ] No Playwright artifact, `package.json`, or `node_modules` is ever created inside a client repo.
- [ ] No new entry in `requirements.txt`.
- [ ] `build_context` has real-argument test coverage for both `es_bug` values.
- [ ] A bug session's verification produces a written test plan the user can read, not just a
      pass/fail claim.
- [ ] A ticket round saved after a bug session records `qa_verified` truthfully (`True`, `False`,
      or `None` when unknown) — never guessed from the diff.
