# Archive Report: Dashboard Story Switcher

**Change**: dashboard-story-switcher
**Project**: aicli
**Archived**: 2026-09-19
**Status**: Complete with Accepted Open Risks

## Executive Summary

The dashboard-story-switcher change has been fully implemented, passed verification with non-blocking warnings, and is archived with all 30 tasks complete. The change introduces a single-board story dashboard with 2D keyboard navigation, story cards showing sibling sub-tasks as inline chips, a board switcher modal, and pinned reopened tickets. No CRITICAL issues block archive. Three WARNINGs (W1, W2, W3) describe UX regressions and unresolved risks that were explicitly disclosed during verification and apply phases. The user explicitly waived a manual terminal verification for W3 and approved proceeding to archive accepting the risk as-is.

## Change Overview

### Scope Delivered

- `aicli/services/jira.py`: Added `"parent"` field to `fetch_my_issues` request (~8 lines)
- `aicli/tui/widgets.py`: Replaced `TicketPanel` render/selection core; dropped `ListView`, implemented dual-reactive-index navigation with story cards and sibling chips (~330 add / ~150 del)
- `aicli/tui/modals.py`: New `BoardSwitcherModal` with case-insensitive board filtering (~128 lines)
- `aicli/tui/screens.py`: Added `"b"` binding, wired board switcher, fixed `action_focus_tickets`/`action_jump_top`/`action_jump_bottom` integration gaps (~22 lines)

### Spec Compliance

All 8 requirements and 16 scenarios from `tui-ticket-dashboard/spec.md` are implemented.
- 10/16 scenarios COMPLIANT via automated unit tests covering pure logic functions
- 6/16 scenarios PARTIAL via source-code inspection (no permanent test harness, per design decision)
- 0/16 scenarios UNTESTED or FAILING

### Testing Results

- 109/109 pytest suite passed (excluding pre-existing broken `test_commands.py`)
- 32 new/modified focused tests + 6 subtests, all passing
- New test files: `test_jira_parent_field.py`, `test_ticket_panel_nav.py`, `test_board_switcher_filter.py`
- Build check: all 4 modified modules import cleanly

### Task Completion

All 30 tasks across 6 phases complete:
- Phase 1 (jira.py parent field): 2/2 done
- Phase 2 (pure helpers): 9/9 done (including `test_ticket_panel_grouping.py` retirement)
- Phase 3 (TicketPanel core): 9/9 done
- Phase 4 (BoardSwitcherModal): 4/4 done
- Phase 5 (MainScreen wiring): 4/4 done
- Phase 6 (integration verification): 2/2 done

## Specs Synced to Main Repository

| Domain | Action | Source | Destination |
|--------|--------|--------|-------------|
| `tui-ticket-dashboard` | Created (new domain) | `openspec/changes/dashboard-story-switcher/specs/tui-ticket-dashboard/spec.md` | `openspec/specs/tui-ticket-dashboard/spec.md` |

The spec file is an 8-requirement, 16-scenario specification defining single-board story dashboard behavior, board switching, 2D navigation, reopened ticket pinning, sibling card display, and graceful degradation.

## Findings & Risk Assessment

### CRITICAL Issues

None. The change is safe to archive.

### WARNING Issues

**W1: Legacy "Globally Active Ticket" Marker is Gone (Real UX Regression, NOT a Spec Violation)**

**Status**: Disclosed, not blocking, follow-up ticket recommended

The pre-existing UI displayed a visual marker (triangle glyph `▶`) on whichever ticket was the user's globally active ticket (from `ticket_activo_<pid>.json`), independent of keyboard cursor position. In the new implementation, this marker is now driven solely by keyboard focus. The `_active` flag is still computed during fetch but never used in render; it is dead code.

**Justification for archive clearance**: All 8 spec requirements + 16 scenarios explicitly address board switching, story hierarchy, 2D navigation, reopened pinning, and chip rendering. The only requirement touching "active ticket" is "Active Board Resolution," which covers only which board is shown on mount, not per-row visual indicators. The spec does NOT require the legacy active-ticket marker to be preserved.

**Recommendation**: Open a follow-up ticket to restore the active-ticket marker (would require threading `_active_tid` through `Row` shape and `build_board_rows` signature, avoided in this change per design's interface constraint).

---

**W2: Graceful Degradation "Failed Fetch" Path is Untriggerable in Production Today (Functionally Equivalent, Conceptually Incomplete)**

**Status**: Disclosed, design tradeoff, follow-up recommended

The spec requires: "A `fetch_subtasks` failure for one parent MUST degrade only that card to a flat single-row rendering (ticket id + summary, no chips)."

Implementation has the code path (`try/except` in `_fetch()`, `degraded` flag in Row), and it is unit-tested via synthetic `build_board_rows` calls with a fake `failed` set. However, the real trigger never fires: `jira.fetch_subtasks` wraps its entire body in `try/except Exception` and returns `[]` on any failure, never raising. When `siblings.get(parent_key, [])` returns `[]`, the card renders with zero chips—functionally graceful (no crash, no panel break) but visually indistinguishable from a story with legitimately zero subtasks, and without the degraded-flag visual notice.

**Justification for archive clearance**: Functionally equivalent (no crash, panel remains usable), honestly disclosed by apply, and a deliberate tradeoff (jira.py changes scoped to parent field addition only, per proposal).

**Recommendation**: Follow-up to jira.py error contract (e.g., raise a distinguishable exception or return a sentinel value) if the degraded-card UX matters downstream.

---

**W3: Unresolved Textual Compositor Crash Risk in Test Harness, Unknown if Real Terminal Affected (User-Accepted Risk)**

**Status**: Disclosed, unresolved, user explicitly waived manual verification and accepted risk

**The issue**: During sdd-verify, 4 independent throwaway `App.run_test()` scripts were written to validate keyboard navigation (Up/Down/Left/Right/Enter, board switcher filter/confirm/cancel). Every attempt that mounted a real `TicketPanel` crashed with:
```
AttributeError: 'NoneType' object has no attribute 'render_strips'
[inside Textual 8.2.8's Screen._on_screen_resume/_refresh_layout]
```

**Root cause analysis**: Isolated to `TicketPanel`'s combination of:
- `can_focus = True` (required for 2D nav)
- Focus/focus-within CSS rules for border styling
- Reactive indices (`_focus`, `_sub`)

A minimal widget with the same `compose()` structure but without CSS/can_focus/reactives did NOT crash. A minimal reactive `Static` also did NOT crash. So the crash is specific to this combination under this environment's Textual 8.2.8.

**Contradiction in evidence**: 
- `sdd-apply` reported: "some Textual harness fragility observed, but recommend a real interactive pass"
- `sdd-verify` found: "crash on every mount attempt, crash happens before any keypress"
- Both agree the exact error matches and reproduces consistently

**Why the contradiction exists**: Neither apply nor verify had access to a real terminal in this sandbox environment. apply used a short throwaway harness session; verify attempted 4 longer harness sessions. Both encountered the same crash signature, but neither can answer whether a real terminal (not headless harness) hits the same code path.

**User's explicit decision**: When asked to run a real-terminal keyboard-nav check before archive to resolve W3 one way or the other, the user explicitly waived this manual verification and requested proceeding to archive accepting the risk as-is.

**Justification for archive clearance per user waiver**: 
1. No CRITICAL issue blocks archive (risk is WARNing-level, unresolved but disclosed).
2. The underlying keyboard navigation logic is solidly unit-tested (all pure nav functions: `move_focus`, `move_sub`, `target_ticket_id` covered).
3. The design pre-emptively rejected a permanent Pilot harness, citing exactly this fragility class.
4. The user's explicit waiver, documented here, reflects their informed decision to accept the risk.

**Record for future readers**: This change shipped with **one unverified, unresolved risk** (W3). The risk is whether the Textual test harness crash also manifests in a real terminal session. This is NOT a completed live verification; it is a deliberate user decision to proceed with testing incomplete. Strongly recommend a quick manual smoke test in a real terminal (press "t" to focus TicketPanel, arrow around, press "b" to open board switcher) before or shortly after the change ships, to confirm the real terminal driver does not hit the same code path.

---

### SUGGESTION Issues

1. **Re-thread `_active` through Row/build_board_rows in a follow-up** to restore the legacy active-ticket marker as a visually distinct indicator alongside the new focus-based marker.
2. **Correct scenario/requirement counts downstream**: The spec contains 8 requirements / 16 scenarios (verified by line-by-line read of `spec.md`). An upstream brief cited 20 scenarios (likely a miscount). Use the actual spec.md file as authoritative.

## Artifact Inventory

### In Archive Folder: `openspec/changes/archive/2026-09-19-dashboard-story-switcher/`

- [x] `proposal.md` — Intent, scope, capabilities, approach, risks, rollback, dependencies
- [x] `design.md` — Technical approach, architecture decisions, data flow, file changes, interfaces, testing strategy
- [x] `tasks.md` — 6 phases, 30 tasks, all complete, TDD-ordered breakdown
- [x] `verify-report.md` — PASS WITH WARNINGS; 0 CRITICAL, 3 WARNING, completeness metrics, spec compliance matrix, test results (109/109 passing)
- [x] `state.yaml` — Change metadata, phase timeline, phase outcomes, execution mode, delivery strategy
- [x] `exploration.md` — Current state findings, scope split recommendations, risks, readiness confirmation
- [x] `specs/tui-ticket-dashboard/spec.md` — 8 requirements, 16 scenarios, board switcher modal, active board resolution, story cards with chips, pinned reopened, 2D nav, enter semantics, graceful degradation, non-regression

### Main Specs Tree: `openspec/specs/`

- [x] `openspec/specs/tui-ticket-dashboard/spec.md` — Synced from delta spec (new domain created)

## Final State Authority

This archive report records the change's state AT CLOSE per the Final-State Authority hierarchy:

1. **Verify report** (most recent snapshot): PASS_WITH_WARNINGS, 0 CRITICAL, 3 WARNING, 30/30 tasks, 109/109 tests
2. **Apply progress** (intermediate): 30/30 tasks complete, 3 disclosed deviations, asked for real-terminal check
3. **User's explicit waiver** (launch prompt): User declined manual terminal check, requested archive with W3 risk accepted
4. **Proposal/Design/Tasks** (earlier plans): All delivered as specified

**Resolved facts for archive**:
- 30/30 tasks complete (per apply, verified by tasks.md checkbox review)
- 109/109 tests passing (per verify report)
- 0 CRITICAL blockers (per verify report)
- 3 non-blocking WARNINGs documented (W1, W2, W3)
- W3's unresolved Textual crash is a user-accepted risk (per explicit waiver)

## SDD Cycle Summary

| Phase | Status | Key Outcome | Observer ID |
|-------|--------|-------------|-------------|
| Explore | done | Critical finding: ListView can't do 2D nav; must use dual-reactive-index pattern | — |
| Propose | done | ~590 line estimate, over 400 budget; size:exception requested & granted | 276 |
| Spec | done | 8 requirements / 16 scenarios, all user decisions incorporated | 278 |
| Design | done | Dual-reactive indices in TicketPanel, BoardSwitcherModal, 3 integration gaps fixed | 280 |
| Tasks | done | 6 phases, 30 tasks, TDD-ordered, test_ticket_panel_grouping.py intentionally retired | 281 |
| Apply | done | 30/30 tasks, 109/109 tests, 1 real bug found+fixed, 3 deviations disclosed | 282 |
| Verify | done | PASS_WITH_WARNINGS; 0 CRITICAL, 3 WARNING (W1 UX loss, W2 untriggerable path, W3 unresolved crash + user waiver) | 285 |
| Archive | done | All artifacts synced, change moved to archive folder, report recorded | (this document) |

## Notes for Maintenance

1. **W1 Follow-up**: Active-ticket marker can be restored by threading `_active_tid` through Row and `build_board_rows` in a separate PR. No schema changes needed.
2. **W2 Follow-up**: If degraded-card UX is important, jira.py's error contract should be updated to distinguish fetch failures from legitimately empty subtask lists.
3. **W3 Follow-up**: CRITICAL: Run a real-terminal smoke test with `t` (focus TicketPanel), arrow keys, and `b` (board switcher) to confirm the Textual crash does not appear in the live running app. This is NOT optional if this change ships before an interactive check.

## Closure

The SDD cycle for dashboard-story-switcher is complete. The change is archived with all artifacts in place, all tasks done, tests passing, and findings honestly recorded. W1 and W2 are minor (not spec violations, follow-ups recommended). W3 is an unresolved, but accepted risk per explicit user waiver.

Ready for deployment after a real-terminal smoke test (W3 only).
