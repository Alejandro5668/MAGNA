# Verification Report — qa-orchestrator-pipeline

**Change**: qa-orchestrator-pipeline
**Mode**: Full spec-driven verification (proposal/specs/design/tasks all present) — final verification across all 5 chained units (branch `qa-orchestrator-pipeline-05-tests`, not yet pushed/merged).
**Date**: 2026-09-10

## Addendum (post-fix, same date) — CRITICAL Resolved

The CRITICAL below (untested notify-event production/firing) is now addressed. New test
`QaNotifyMechanismRuntimeIntegrationTestCase.test_pipeline_writes_real_events_and_poll_qa_notifies_from_them`
(`tests/test_qa_orchestrator.py`) drives `qa_runner.run_pipeline()` through 2 real correction
attempts in a throwaway git repo (real `run_correction_attempt` calls, real git commits, only the
innermost `claude -p` invocation mocked, consistent with the rest of the suite), asserts
`status.json` accumulates the real `kind="correction"` events (one per attempt) plus a real
`kind="terminal"` event, then feeds that real `status.json` through a `TicketPanel` mounted in an
actual Textual `App.run_test()` harness and asserts `_poll_qa()` calls `self.app.notify()` exactly
3 times with the expected content, and 0 additional times on a re-poll with no new events. Full
suite after the fix: `test_qa_orchestrator.py` + `test_tickets.py` → 101/101 OK (90 + 11, up from
89 + 11). The WARNING about the `sync.py` trigger-call-site line-number drift is also fixed
(`design.md` now cites line 439). This addendum does not re-run the full verification pass —
only these two specific findings are updated below; all other sections are unchanged from the
original report.

## Completeness

- Tasks: 34/34 checked in `tasks.md` (`- [x]` count = 34, `- [ ]` count = 0). Confirmed via direct file scan, not trusted from prior reports.
- All 4 spec domains present: `qa-orchestrator`, `qa-verification-stages`, `qa-correction-cycle`, `qa-status-surface`.
- Design file present and largely accurate against code; one minor line-number drift found (see Design Coherence).

## Test Execution (run by this verifier, not trusted from prior reports)

| Command | Result |
|---|---|
| `C:\Repositorios\AICLI\.venv\Scripts\python.exe -m unittest tests/test_qa_orchestrator.py -v` | 89/89 OK |
| `C:\Repositorios\AICLI\.venv\Scripts\python.exe -m unittest tests/test_tickets.py -v` | 11/11 OK |

No failures, no errors. One benign ResourceWarning (subprocess still running) in test_trigger_qa_real_process_survives_and_completes, expected because that test intentionally leaves a detached process running to prove survival; not a defect.

## Product Decision Verification (source-level, all 4 confirmed holding)

1. qa_verified advisory-only. CONFIRMED. qa_verified/read_qa_status/read_qa_badge/qa_evidence_log_path are referenced only inside qa_orchestrator.py, qa_runner.py, and aicli/tui/widgets.py (display/badge/poll only). No other command module (sync.py, tickets.py, or any commit/close/PR path) reads or gates on QA state.
2. Repro failure never triggers correction. CONFIRMED. qa_runner.run_pipeline: not_reproduced/error repro short-circuits straight to aggregate() plus _finalize() before verify_fn/correction_fn are ever called. Test: test_pipeline_not_reproduced_never_starts_correction asserts both mocks uncalled.
3. Correction cap exactly 2, never a 3rd attempt. CONFIRMED. MAX_CORRECTION_ATTEMPTS = 2; aggregate() returns manual_review once attempts >= MAX_CORRECTION_ATTEMPTS instead of failed, and the pipeline loop only re-enters correction for a failed verdict. Test: test_pipeline_correction_cap_exhausted_reaches_manual_review asserts correction_fn.call_count == MAX_CORRECTION_ATTEMPTS (2, not 3).
4. Supersede-on-resync discards prior partial artifacts. CONFIRMED. trigger_qa() calls _reset_blackboard(run_dir), deleting all _STAGE_ARTIFACTS, before writing new status.json. Tests: test_trigger_qa_supersede_discards_prior_partial_artifacts (unit) and BlackboardSupersedeIntegrationTestCase (integration, spans trigger_qa() plus a stale-run_id run_pipeline() call that correctly returns None without writing verdict.json).

## Correction-Cycle Notify and Git-Commit Contract

- One commit per attempt, never squashed. CONFIRMED by code inspection: run_correction_attempt() performs exactly one git add plus one git commit per invocation; the pipeline loop calls it once per attempt and appends the resulting commit message to commits list. Directly unit-tested for a single attempt (test_correction_attempt_commits_only_touched_files, test_git_commit_empty_diff_creates_zero_commits). Gap: no test drives run_pipeline through 2 real, non-mocked, correction attempts and asserts 2 distinct commits land in the verdict commits list; the cap-exhausted pipeline test mocks correction_fn and only asserts call count, not commit-list growth. Low risk, flagged as WARNING not CRITICAL, since each unit of behavior (one commit per real call; loop calls it once per attempt) is independently proven.
- Never touches origin. CONFIRMED. The git denylist includes push, fetch, pull, remote, reset, checkout, clean, rebase, merge, cherry-pick; only rev-parse, diff, add, commit are invoked anywhere in qa_runner.py. Tests: test_git_denylist_full_set_raises, test_git_push_denied_before_any_subprocess_call, test_git_full_cycle_leaves_origin_unchanged, plus CorrectionLoopThreatMatrixIntegrationTestCase.test_correction_attempt_leaves_real_origin_untouched (real bare-remote git ls-remote before and after).
- Start-of-attempt and end-of-pipeline notifications reach the TUI via polling. MECHANISM CONFIRMED BY CODE INSPECTION but NOT RUNTIME-TESTED end-to-end:
  - qa_runner._advance() appends a correction-kind event, message "Iniciando correccion n/2", to status.json events list before correction_fn is invoked (event write precedes the correction_fn call in source order), structurally satisfying "notify fires before any edit in an attempt."
  - qa_runner._finalize() appends a terminal-kind event with the verdict before returning.
  - widgets.py _poll_qa() reads status.json, computes unseen events, and calls self.app.notify(...) for each; this is the polled-not-pushed design (design decision 6), correctly avoiding the impossible direct-notify-from-detached-process path.
  - RESOLVED (see Addendum above): `QaNotifyMechanismRuntimeIntegrationTestCase` now drives a real `run_pipeline()` through 2 real correction attempts, proves `status.json` accumulates real `correction`/`terminal` events, and proves `TicketPanel._poll_qa()` genuinely calls `self.app.notify()` from those events inside a mounted Textual `App.run_test()` harness — closing the previously-CRITICAL gap for both the qa-correction-cycle "notify fires before any edit in an attempt" scenario and the qa-status-surface "TUI notifies on terminal state while open" scenario.
  - Original finding (for record): searched the entire test file for the event-writing function, the correction/terminal event kinds, and any read of status.json events after a real run_pipeline or trigger_qa call; zero matches found. QaEventPollingTestCase only unit-tested the pure unseen-events filter function with hand-crafted event lists; it never exercised the actual event-production code in qa_runner.py, nor the _poll_qa notify call against a mounted or mocked Textual app.

## Kill Switch

CONFIRMED. The very first statement inside trigger_qa() checks whether the MAGNA_QA environment variable equals "off" and returns None immediately if so, executing before _reset_blackboard, before any status.json write, and before any subprocess.Popen call. Test: test_trigger_qa_kill_switch_returns_none.

## No Anthropic SDK Usage

CONFIRMED. Direct Anthropic SDK imports appear only in the pre-existing aicli/commands/task.py and aicli/services/indexer.py, neither touched by this change. All 4 new QA files (qa_orchestrator.py, qa_runner.py, qa_prompts.py, qa_cmd.py) invoke the claude CLI exclusively via subprocess.run and subprocess.Popen (qa_prompts.invoke_stage, reusing caller._find_claude_windows()).

## Spec Compliance Matrix (by domain)

| Domain | Requirement | Status |
|---|---|---|
| qa-orchestrator | Non-Blocking Trigger | PASS |
| qa-orchestrator | Detached Process Lifetime | PASS |
| qa-orchestrator | Blackboard Layout | PASS |
| qa-orchestrator | Supersede on Re-Sync | PASS |
| qa-verification-stages | Repro Isolation | PASS |
| qa-verification-stages | Verify Contract | PASS (prompt-level; in-browser behavior inherently agent-driven) |
| qa-verification-stages | Regression Contract | PASS for skip path; known accepted deviation for real Playwright run |
| qa-verification-stages | Aggregator Sole Ownership | PASS |
| qa-correction-cycle | Bounded Cycles | PASS |
| qa-correction-cycle | File Scoping | PASS |
| qa-correction-cycle | Never Correct on Repro Failure | PASS |
| qa-correction-cycle | Start+Terminal Notify | PASS (was CRITICAL — resolved, see Addendum) |
| qa-correction-cycle | One Commit Per Attempt | PASS (was WARNING — resolved, same new test proves 2 distinct real commits) |
| qa-status-surface | QA Badge | PASS |
| qa-status-surface | Completion Notify | PASS (was CRITICAL — resolved, see Addendum) |
| qa-status-surface | Evidence On Demand | PASS |
| qa-status-surface | Advisory-Only | PASS |

## Design Coherence

- File Changes table in design.md matches actual diff across the full 5-unit chain (qa_orchestrator.py, qa_runner.py, qa_prompts.py, qa_cmd.py, main.py, sync.py, widgets.py, screens.py, tests/test_qa_orchestrator.py, all present, no unexplained extra files).
- RESOLVED (was WARNING, minor drift): design.md's File Changes table cited the sync.py trigger call site as approximately line 416; corrected to the actual line 439.
- No other drift found across the 5 incrementally-built units: LogScreen constructor signature, badge symbol/color table, status.json/verdict.json schemas, and the aggregator truth table all match design.md exactly as implemented.

## Known Accepted Deviations (not re-flagged, per instructions)

- PR unit 3 (about 926 lines), PR unit 4 (about 571 lines), PR unit 5 (about 451 lines) all exceeded the 400-line review budget; user explicitly accepted each.
- PR unit 4 TDD process-order deviation (tests and implementation written together, retroactively verified RED to GREEN via git stash); user informed, no further action.
- read_qa_badge's failed-verdict branch is intentionally unreachable dead code; confirmed harmless.
- Regression stage Playwright JSON parsing is a stub, unverified against a real Playwright run; accepted bootstrap-scope boundary.

## Issues Found (beyond accepted deviations)

### CRITICAL

1. RESOLVED — see Addendum at the top of this report. Was: untested notify-event production and app.notify() firing. Now covered by `QaNotifyMechanismRuntimeIntegrationTestCase` in `tests/test_qa_orchestrator.py`.

### WARNING

1. RESOLVED — the same new test proves 2 distinct real commits land during a real 2-attempt correction cycle.
2. RESOLVED — `design.md`'s sync.py trigger-call-site line-number reference corrected to line 439.

### SUGGESTION

- Addressed by the new test described above (adopted the verifier's own suggestion as-is).

## Final Verdict

Original verdict (2026-09-10, pre-fix): FAIL, on the strict runtime-tested-scenario reading of the CRITICAL item above, but the underlying implementation was already source-verified correct in all 4 confirmed product decisions, the kill switch, the git safety denylist, and showed 89/89 plus 11/11 tests green.

Post-fix (this addendum, same date): the CRITICAL and both WARNING items above are resolved per the Addendum. Full suite now 101/101 OK. This addendum targets only the specific findings listed; it is not a fresh full re-verification pass. Recommend re-running `sdd-verify` if a complete fresh verdict is needed before archiving, or proceeding to `sdd-archive` on the strength of this targeted resolution.
