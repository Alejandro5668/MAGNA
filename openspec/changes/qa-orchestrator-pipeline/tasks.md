# Tasks: QA Orchestrator Pipeline

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1050 (9 files: 4 new services/cmd, 3 modified, 1 new test file) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR1 Foundation → PR2 Launcher → PR3 Stages+Runner → PR4 TUI wiring → PR5 Tests |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

`single-pr` normally maps straight to `size:exception`, but ~1050 est. lines is >2.5x budget — surfaced, not defaulted. Orchestrator must ask: (a) accept `size:exception` as one PR, or (b) `feature-branch-chain` via the 5 units below.

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Kill switch, blackboard schemas, `_parse_agent_json`, `_git` deny-list + threat-matrix RED tests | PR1 | `pytest tests/test_qa_orchestrator.py -k "git or parse_agent_json"` | N/A — pure unit tests, no live subprocess | Delete `qa_orchestrator.py`; no other file depends on it yet |
| 2 | Hidden `qa-run` entrypoint + detached Popen launcher | PR2 | `pytest tests/test_qa_orchestrator.py -k launch` | Spike S3 sleeper script via real `ctx` invocation | Revert `qa_cmd.py`, `main.py` one-line registration |
| 3 | Stage prompts (repro/verify/regression/corrector) + `qa_runner.py` driver + aggregator | PR3 | `pytest tests/test_qa_orchestrator.py -k "aggregator or stage"` | Manual: one real `claude -p` call per stage prompt against a throwaway ticket | Delete `qa_runner.py`, `qa_prompts.py` |
| 4 | `sync.py` trigger call site + TUI badge/poll/LogScreen wiring | PR4 | `pytest tests/test_qa_orchestrator.py -k tui` | Manual: `ctx sync` then open TUI, confirm badge + evidence screen | Revert the 3 touched call sites; additive only |
| 5 | Remaining unit/integration tests from design's test plan | PR5 | `pytest tests/test_qa_orchestrator.py` | N/A — test-only PR | Delete added test functions |

## Phase 1: Mandatory Spikes (BLOCKING — before any further code)

- [x] 1.1 Spike S1: `claude -p "List the skills and MCP servers you can use right now."` in a scratch dir; record whether `security-review`/CodeGraph resolve headlessly. Either outcome is fine — corrector already assumes no skill/MCP by default (decision 5); this only relaxes prompt wording, blocks nothing.
- [x] 1.2 Spike S2: capture `claude --help`, pin exact non-interactive flags (permission mode, output format). If they differ from the assumed bare `-p`, update 4.4 and all stage prompts' wrapper call before Phase 4 starts — do not code stages against unverified flags.
- [x] 1.3 Spike S3: launch a 30s sleeper via the exact detached `Popen` from a real `ctx` invocation; close the terminal; confirm survival and `run.log` writes. If it fails on Windows, redesign the launcher before Phase 3 — nothing downstream may assume this Popen shape.

## Phase 2: Foundation — Kill Switch, Schemas, Git Safety

- [x] 2.1 `qa_orchestrator.py`: kill switch — `trigger_qa()` returns `None` when `os.getenv("MAGNA_QA") == "off"`.
- [x] 2.2 `qa_orchestrator.py`: blackboard layout — `~/.mycontext/qa_results/<TICKET>/` via `tickets._safe_id()`, atomic writes via `tickets._write_ticket`'s tmp-then-`replace()`.
- [x] 2.3 `qa_orchestrator.py`: define `status/repro/verify/regression/verdict` JSON schemas per design's Interfaces section.
- [x] 2.4 `qa_orchestrator.py`: `_parse_agent_json()` — strip fences, `raw_decode()`; unparseable writes stage `status:"error"` + `raw/<stage>.txt`.
- [x] 2.5 RED test: ticket id with `&`/spaces produces a safe blackboard dir name and non-shell argv (subprocess/shell threat).
- [x] 2.6 RED test: `_git(["push",...])` raises; full correction cycle leaves `origin/<branch>` unchanged (push-state threat).
- [x] 2.7 RED test: unrelated dirty file stays unstaged; empty diff ⇒ zero commits, attempt still counted (commit-state threat).
- [x] 2.8 RED test: correction commit lands only in the tmp repo at `cwd=project_path` (git-repo-selection threat).
- [x] 2.9 `qa_orchestrator.py`: implement `_git(args, cwd)` deny-listed helper (`push/fetch/pull/remote/reset/checkout/clean/rebase/merge/cherry-pick` raise) — makes 2.5–2.8 pass.

## Phase 3: Detached Launcher + Hidden Entrypoint — ALL DONE

- [x] 3.1 Create `aicli/commands/qa_cmd.py` — hidden `qa-run <TICKET> --project-path <p> --run-id <id>` Typer command. This unit's scope: placeholder heartbeat loop (no real stages yet, Phase 5) that proves the detach mechanic and honors cooperative supersede (exits without writing if `status.json`'s `run_id` no longer matches).
- [x] 3.2 `main.py`: `app.add_typer(qa_cmd.app, name="qa-run", hidden=True)` — confirmed hidden from `main.py --help`.
- [x] 3.3 `qa_orchestrator.py`: implemented `trigger_qa()` detached `Popen` launcher (re-enter via `sys.executable`, frozen-vs-dev argv via `_qa_run_argv`, stdout/stderr → `run.log`, exact S3-validated creationflags). Spike S3 passed, no redesign needed. **Deviation found and fixed**: the internal argv puts `--project-path`/`--run-id` BEFORE the `ticket_id` positional (not after, as tasks.md's literal invocation example showed) — Click/Typer's group-dispatch parsing (same `@app.callback(invoke_without_command=True)` pattern already used by `task.py`/`archive.py`) mis-parses `qa-run <TICKET> --opt val` as "TICKET is COMMAND, then unknown args", a pre-existing quirk of this project's whole CLI convention (reproduced identically with `ctx task "text" --archivo x.py`), not something new. Confirmed real end-to-end: `qa-run --project-path <p> --run-id <id> <TICKET>` works; the wrong order does not. `qa_cmd.py`'s help text/param names are unchanged — only the internally-generated argv order changed.
- [x] 3.4 Launch-failure handling: wrapped 3.3 in try/except around the `open(run.log)` + `Popen(...)` call — any exception writes `status.json` `state:"error", reason:"launch_failed"` and `trigger_qa()` returns `None`; never raises into the caller.

## Phase 4: Stage Prompts (depends on spikes 1.1, 1.2) — ALL DONE (PR3)

- [x] 4.1 `qa_prompts.py`: repro role contract + template — zero fix-diff/commit references, outputs `reproduced`/`not_reproduced`. **RED test forced a wording fix**: the first draft used the words "diff"/"commit" to instruct the agent NOT to look for them, which itself violated the isolation requirement's letter — reworded to "cambio de código", zero occurrences of "diff"/"commit" anywhere in the repro prompt.
- [x] 4.2 `qa_prompts.py`: verify role contract + template — browser + read-only DB only, outputs `pass`/`fail`.
- [x] 4.3 `qa_prompts.py`: corrector role contract + inlined `SECURITY_CHECKLIST` + diff-scoped context (`git diff` of touched files + `archivos_tocados`). Assumes no skill/MCP regardless of spike 1.1's result (design decision 5); result only adds an optional hint.
- [x] 4.4 Headless invocation helper — `subprocess.run([claude, "-p", ...], capture_output=True, timeout=STAGE_TIMEOUT)` reusing `caller._find_claude_windows()`. Confirmed bare `-p` sufficient (spike S2, PR1) — plus a new spike run by THIS unit confirming Edit/Write tool use also works headlessly with no hang/no explicit permission-mode flag (see apply-progress; this was the explicitly-flagged unverified gap from PR2).

## Phase 5: Stage Driver + Aggregator — ALL DONE (PR3)

- [x] 5.1 `qa_runner.py`: stage sequencing repro → verify → regression (`npx playwright test`, `status:"skipped"` when `MAGNA_E2E_REPO` unset). **Scope note**: the Playwright JSON-reporter parsing is a reasonable stub over the documented `--reporter=json` shape (`stats.expected`/`stats.unexpected`) — not verified against a real Playwright run; full E2E integration is out of scope for this unit.
- [x] 5.2 `qa_runner.py`: aggregator truth table → `verdict.json`, sole writer of `qa_verified`. Bootstrap default: `regression: skipped` still permits `qa_verified: true` if `verify: pass` — implemented exactly as confirmed. Full truth table incl. error/timeout paths gets dedicated test coverage in Phase 8 (PR5); this unit's tests cover only the paths the pipeline-level RED tests (5.4/5.5) plus the happy path exercise.
- [x] 5.3 `qa_runner.py`: correction loop — max 2 attempts, edits scoped to `archivos_tocados`, one `_git` commit per attempt (`fix(qa-auto): correccion automatica <n>/2 - <motivo>`). **Deviation**: per-attempt/terminal notification is implemented as `status.json` `events[]` entries (`kind:"correction"`/`kind:"terminal"`) appended by the runner, NOT a direct `self.app.notify()` call — the runner is a detached process with no `self.app` handle (design decision 6 explicitly rules this out). Phase 7's TUI poller (PR4) is what turns each unseen event into an actual `app.notify()` call; this unit lays the exact event data Phase 7 consumes.
- [x] 5.4 RED test: `not_reproduced` (doubtful) never starts a correction cycle.
- [x] 5.5 RED test: cap exhausted at 2 → `manual_review`, no 3rd attempt, never blocked/reverted.

## Phase 6: `_sync_impl` Trigger Call Site

- [ ] 6.1 `aicli/commands/sync.py`: one guarded `trigger_qa(...)` call after `clear_active_ticket()` (~line 416), inside `if save:`; must not block return.

## Phase 7: TUI Polling, Badge, LogScreen Wiring

- [ ] 7.1 `aicli/tui/widgets.py`: `_fetch()` sets `t["_qa"]`; `_row()` appends badge (symbol + colour, never colour alone).
- [ ] 7.2 `aicli/tui/widgets.py`: `on_mount` adds `set_interval(5.0, self._poll_qa)`; notifies for each unseen `events[].seq`.
- [ ] 7.3 `aicli/tui/widgets.py`: footer `[e] evidencia`; `on_key` opens `LogScreen` for the ticket's `evidence.log`.
- [ ] 7.4 `aicli/tui/screens.py`: `LogScreen.__init__(log_path=None, title="MAGNA — Logs")`; keep existing call site (screens.py:1300) working via defaults.

## Phase 8: Remaining Tests Per Design's Test Plan

- [ ] 8.1 Unit: aggregator truth table incl. error and timeout paths.
- [ ] 8.2 Unit: badge/staleness mapping, frozen clock (`heartbeat` > 600s ⇒ `stale`).
- [ ] 8.3 Integration (`MYCONTEXT_HOME` tmp dir): blackboard lifecycle + supersede — new `run_id` discards prior partial artifacts.
- [ ] 8.4 Integration: `trigger_qa` launch failure writes `state:"error"`, never raises into `_sync_impl` (monkeypatched `Popen` OSError).
