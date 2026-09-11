# Proposal: QA Orchestrator Pipeline

## Intent

Tickets get reopened because the session writing the fix is the same one certifying it. The prior
attempt (`qa-verification-protocol`, reverted 2026-09-10) failed for exactly that: a self-report is not
evidence. Goal — near-0% reopen rate via an **independent** QA check run by separate `claude` CLI
sessions that reproduce, verify in a real browser, and run regression before `qa_verified` is set.

## Scope

### In Scope
- `qa_orchestrator.py`: detached background pipeline; blackboard at `~/.mycontext/qa_results/<TICKET>/`.
- Non-blocking trigger: one call in `_sync_impl` after `save_round`, inside the `if save:` branch.
- Four decoupled stages: repro (no fix knowledge) → verify (browser + read-only DB) → regression
  (Playwright, separate repo) → aggregator (pure Python, sole owner of `qa_verified`).
- Bounded correction: max 2 cycles, edits limited to files the fix already touched; each attempt is
  its own git commit on the ticket branch (never squashed, never auto-pushed) plus a start-of-attempt
  and end-of-pipeline `notify()`.
- TUI: QA badge in `TicketPanel._row()`, `notify()` on completion, evidence via parameterized `LogScreen`.

### Out of Scope
- Anthropic API for QA agents — subscription `claude` CLI subprocesses only.
- LangGraph / CrewAI / AutoGen (evaluated, rejected as overkill).
- Cucumber/Gherkin — deliberately left undecided.
- Any production write; all agent DB checks are read-only.
- Correction on repro failure — that signals a doubtful ticket, not bad code.
- Autonomous multi-ticket/batch processing across the Jira queue — deliberate follow-on change once
  this single-ticket pipeline is proven; see "Explicitly out of scope" section below for why.

## Capabilities

### New Capabilities
- `qa-orchestrator`: trigger, detached process lifetime, blackboard layout, stage sequencing.
- `qa-verification-stages`: role contracts and evidence schema for the four stages.
- `qa-correction-cycle`: bounded correction, file scoping, security pass, no-false-pass invariant.
- `qa-status-surface`: QA state in the TUI.

### Modified Capabilities
- None.

## Approach

**One uniform detached-subprocess launcher for both call sites.** A thread cannot give "returns
immediately AND keeps running" on the bare-CLI path: non-daemon blocks exit, daemon dies at exit. So
`Popen(..., DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)` is used identically from CLI and TUI instead
of a second Textual `@work` path — one mechanism, one guarantee, and the TUI becomes a passive file
poller, not a thread owner.

Stages share nothing but files. Each is a headless `claude -p` session fed via a prompt file; JSON reads
use the `raw_decode` tolerance already proven necessary in `task.py`. Regression re-runs use plain
`npx playwright test` (zero tokens); Playwright MCP only authors/updates tests.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `aicli/services/qa_orchestrator.py` | New | Trigger, stage driver, blackboard |
| `aicli/commands/sync.py` | Modified | One non-blocking call after `save_round` |
| `aicli/tui/widgets.py` | Modified | QA badge via `_fetch()` → `_row()` |
| `aicli/tui/screens.py` | Modified | `LogScreen` takes a log path |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Detached `Popen` on Windows has zero precedent here | High | Design spikes it; redirect stdout/stderr to files |
| `security-review` unreachable from headless subprocess | Med | **Assumption, not fact** — design validates; fallback inlines the checklist |
| CodeGraph MCP not inherited by subprocess | Med | Same spike; corrector degrades to diff-scoped context |
| LLM JSON with trailing noise | High | `raw_decode`; malformed evidence = failure, never a pass |
| Orphaned QA processes | Med | PID/heartbeat file per ticket, stale detection on read |
| Pipeline silently never runs | Med | Aggregator writes a terminal state for every trigger, timeouts included |

## Rollback Plan

Delete `qa_orchestrator.py`, revert the one `sync.py` call and two TUI edits, drop
`~/.mycontext/qa_results/`. No schema or signature changes, so rollback is additive-only removal.

## Dependencies

- `claude` CLI on PATH in non-interactive `-p` mode; `claude-in-chrome`; Node + Playwright in a
  separate repo outside the client codebase.

## Success Criteria

- [ ] `ctx sync` returns immediately and the pipeline survives closing the terminal.
- [ ] `qa_verified: true` only after a real passing verify stage.
- [ ] Most tickets pass with zero correction cycles.
- [ ] Repro failures surface as doubtful tickets, never as corrections.
- [ ] Every QA decision has a readable evidence JSON in the TUI.

## Product decisions (confirmed with user 2026-09-10)

1. QA failing after 2 correction cycles → ticket flagged for manual review. Never blocked, never
   auto-reverted.
2. `qa_verified` is advisory only in this first slice — does not gate ticket close, commit, or PR.
3. Repro stage unable to reproduce the bug → separate "dudoso" (doubtful) state. Never triggers the
   correction cycle — a doubtful ticket is a ticket-quality signal, not a code problem.
4. A new `ctx sync` while a QA run is still in progress for the same ticket → the new run supersedes
   the old one (old run's partial artifacts are discarded, not merged).

## Correction-cycle notification & audit trail (confirmed with user 2026-09-10)

- **Two notifications per correction cycle**, both via `self.app.notify()`: one when a correction
  attempt starts ("QA falló en `<stage>`, aplicando corrección automática `<n>/2`"), one when the
  overall pipeline reaches a terminal state. Silent-until-the-end was explicitly rejected — the user
  wants visibility the moment code is being edited unattended, even though it's non-blocking.
- **Every correction attempt is its own git commit** on the ticket's branch (never squashed into the
  original fix commit, never auto-pushed) — message shape `fix(qa-auto): corrección automática <n>/2 —
  <motivo>`. This is the audit/rollback mechanism: the user reviews via normal `git log`/`git diff`,
  not by trusting the JSON evidence blindly.
- Explicitly rejected: pausing to ask for permission before each correction — defeats the "runs
  unattended while I work on something else" goal that is the whole point of this change.

## Explicitly out of scope for this change (confirmed with user 2026-09-10)

- **Autonomous multi-ticket / batch processing** ("varios casos de Jira" picked up and fixed+verified
  end to end without the user driving each one via `ctx task`/`ctx sync`) — the user wants this, but as
  a deliberate follow-on change once this single-ticket pipeline is proven reliable in practice. Reason
  given: the correction agent (stage 4) is the least-proven part of this design; running it unattended
  across N tickets concurrently before it's validated on one multiplies its blast radius, and parallel
  autonomous tickets risk real git/branch conflicts. The follow-on change should reuse this pipeline
  per-ticket, sequentially, not reimplement it.
