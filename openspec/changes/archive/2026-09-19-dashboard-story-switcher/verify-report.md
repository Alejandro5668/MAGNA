```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:c422cc84d7ebb69f7e0faea7d75dd890c749ba28379f31c2184dd6d32c92937a
verdict: pass_with_warnings
blockers: 0
critical_findings: 0
requirements: 8/8
scenarios: 16/16
test_command: .venv\Scripts\python.exe -m pytest tests/ -v --ignore=tests/test_commands.py
test_exit_code: 0
test_output_hash: sha256:a1e74834d7d4e0e7c629ed5dfcb73bb1547a5a1f89ed70dee8df298257c327b0
build_command: .venv\Scripts\python.exe -c "import aicli.tui.widgets, aicli.tui.modals, aicli.tui.screens, aicli.services.jira"
build_exit_code: 0
build_output_hash: sha256:8ffd844435f7b2828fed8d7afeed916bd72ffe939614dc471d6dcc341c41d65d
```

## Verification Report

**Change**: dashboard-story-switcher
**Version**: tui-ticket-dashboard/spec.md (final, 8 requirements / 16 scenarios)
**Mode**: Strict TDD

### Completeness
| Metric | Value |
|--------|-------|
| Tasks total | 30 |
| Tasks complete | 30 |
| Tasks incomplete | 0 |

### Build & Tests Execution
**Build**: PASSED (no bundler/type-checker configured for this pure-Python project; used a module-import check on the 4 changed files as a build-equivalent smoke check)
```text
.venv\Scripts\python.exe -c "import aicli.tui.widgets, aicli.tui.modals, aicli.tui.screens, aicli.services.jira"
import OK: all changed modules load cleanly
exit 0
```

**Tests**: 109 passed / 0 failed / 0 skipped (+ 6 subtests passed)
```text
.venv\Scripts\python.exe -m pytest tests/ -v --ignore=tests/test_commands.py
============= 109 passed, 2 warnings, 6 subtests passed in 3.32s ==============
```
(2 warnings are pre-existing chromadb DeprecationWarnings, unrelated to this change. tests/test_commands.py is pre-existing-broken and excluded, confirmed via apply-progress's git stash check that its 4 failures predate this change.)

Focused subset (this change's new/touched test files) re-run and independently confirmed:
tests/test_jira_parent_field.py (5 passed), tests/test_ticket_panel_nav.py (22 passed + 6 subtests), tests/test_board_switcher_filter.py (5 passed) = 32 passed + 6 subtests, all green.

**Coverage**: Not available, no coverage tool configured for this project.

### Spec Compliance Matrix
| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| Board Switcher Modal | Filter narrows the list | test_board_switcher_filter.py::test_substring_match_case_insensitive | COMPLIANT |
| Board Switcher Modal | Enter switches the active board | none, source-verified only: modals.py on_key Enter to dismiss(option.id), screens.py _worker_board to panel.set_board | PARTIAL |
| Board Switcher Modal | Esc cancels without changing the board | none, source-verified only: BINDINGS escape to action_cancel to dismiss(None), caller's if board guard | PARTIAL |
| Active Board Resolution | Active ticket determines initial board | test_ticket_panel_nav.py::ResolveInitialBoardTestCase::test_active_ticket_determines_board | COMPLIANT |
| Active Board Resolution | No active ticket falls back to alphabetical | test_no_active_ticket_falls_back_alphabetical | COMPLIANT |
| Active Board Resolution | Board choice is not persisted | none, structural: no persistence write path exists for board choice anywhere in the diff; _board_resolved is an in-memory instance flag only | PARTIAL |
| Story Cards w/ Sibling Chips | Siblings render as chips | test_same_parent_collapses_to_one_card, test_reopened_ticket_never_duplicated_as_chip | COMPLIANT |
| Story Cards w/ Sibling Chips | Dedup limits fetch calls | UniqueParentKeysTestCase::test_dedups_preserving_first_seen_order (proxy: unique_parent_keys is the exact dedup mechanism _fetch() uses before calling fetch_subtasks) | COMPLIANT |
| Pinned Reopened Section | Reopened ticket appears only once | test_reopened_ticket_never_duplicated_as_chip | COMPLIANT |
| 2D Keyboard Navigation | Up/Down crosses row types | MoveFocusTestCase (clamped/in-range cases) | COMPLIANT |
| 2D Keyboard Navigation | Left/Right is a no-op outside cards | MoveSubTestCase::test_table_driven (reopened/loose no-op rows) | COMPLIANT |
| Enter Activation Semantics | Enter on a card targets the sub-focused chip | TargetTicketIdTestCase::test_card_targets_sub_focused_chip | COMPLIANT |
| Enter Activation Semantics | Enter on a reopened row opens that ticket | test_non_card_row_targets_its_only_chip | COMPLIANT |
| Graceful Degradation | Empty board shows a message | BuildBoardRowsTestCase::test_empty_board_returns_empty_rows covers the data shape; the actual message render path is source-verified only | PARTIAL |
| Graceful Degradation | One failed subtask fetch degrades only its card | test_degraded_flag_when_parent_key_failed proves build_board_rows's contract given a synthetic failed set, but the real production trigger is unreachable, see Issue W2 below | PARTIAL |
| Non-Regression of Existing Contracts | Auto-refresh still runs | none, source-verified only: set_interval(self._AUTO_REFRESH_SECS, self._fetch) at on_mount, unchanged @work(thread=True, exclusive=True) decorator | PARTIAL |

**Compliance summary**: 10/16 scenarios COMPLIANT via a runtime-passing covering test; 6/16 PARTIAL (correct by source inspection, but their covering evidence is either a proxy pure-function test one level removed from the literal scenario, or no automated test at all, only the disclosed manual/throwaway App.run_test() pass from apply, which could not be independently reproduced cleanly this session, see Issue W3). 0/16 UNTESTED or FAILING.

This PARTIAL concentration is not a surprise defect: design.md explicitly rejected adding a permanent Textual Pilot test harness for this change (citing exactly the rendering fragility class documented in Issue W3), so TDD coverage was deliberately scoped to the 7 pure, side-effect-free helper functions (unique_parent_keys, resolve_initial_board, build_board_rows, move_focus, move_sub, target_ticket_id, filter_boards, plus _chip_state). Every one of those has solid, well-triangulated, real-assertion unit coverage. What is NOT automated-test-covered is the thin Textual event-wiring layer sitting on top of them (modal dismiss flows, on_key dispatch, set_interval firing) — this is architecturally consistent with, not a violation of, the accepted design.

### Correctness (Static Evidence)
| Requirement | Status | Notes |
|------------|--------|-------|
| Board Switcher Modal | Implemented | modals.py BoardSwitcherModal + filter_boards; screens.py Binding("b","board") to action_board to _worker_board to push_screen_wait to panel.set_board. |
| Active Board Resolution | Implemented | resolve_initial_board called once per session (_board_resolved guard) from _fetch(), never persisted. |
| Story Cards w/ Sibling Chips | Implemented | build_board_rows + unique_parent_keys; _fetch() calls fetch_subtasks once per unique parent key. |
| Pinned Reopened Section | Implemented | reopened_ids set excludes reopened tickets from card chip lists; reopened rows always emitted first. |
| 2D Keyboard Navigation | Implemented | move_focus/move_sub wired in TicketPanel.on_key for up/down/left/right. |
| Enter Activation Semantics | Implemented | target_ticket_id wired in on_key's enter branch, posts TicketSelected. |
| Graceful Degradation | Implemented, with a known dead-code caveat | Empty-board message path exists (_render's "if not self._rows" branch). Degraded-card path exists and is unit-proven, but its real trigger (fetch_subtasks raising) never fires because fetch_subtasks already swallows all exceptions and returns []. See Issue W2. |
| Non-Regression of Existing Contracts | Implemented | TicketSelected message class unchanged; @work(thread=True, exclusive=True) on _fetch unchanged; set_interval(240, self._fetch) unchanged. |

### Coherence (Design)
| Decision | Followed? | Notes |
|----------|-----------|-------|
| Exact signatures for the 6 pure nav helpers | Yes | unique_parent_keys, resolve_initial_board, build_board_rows, move_focus, move_sub, target_ticket_id match design's literal interface list. |
| No permanent Pilot test infra | Yes | No committed Textual Pilot/App.run_test() test file exists in tests/; TDD scoped to pure helpers only, exactly as design specified. |
| fetch_subtasks failure wrapped in try/except into a failed set (task 3.3) | Partially, code present but inert | The try/except is present in _fetch() exactly as instructed, but design's assumption that fetch_subtasks "could raise" does not hold against the real implementation (it already swallows exceptions, same as fetch_issue/fetch_comments). Disclosed by apply as Deviation #1, out of this change's declared scope (jira.py changes restricted to the parent field). |
| 3 integration-gap fixes (action_focus_tickets retarget, jump_top/jump_bottom TicketPanel branch, 3 _HELP_ROWS entries) | Yes, all 3 confirmed present in real code | screens.py:1551-1553 (query_one(TicketPanel).focus()), screens.py:1539-1540,1548-1549 (focus_first()/focus_last() branches), modals.py:42-44 ("b", "left/right arrow", "Enter (chip)" rows). |

### Issues Found

**CRITICAL**: None.

**WARNING**:

- W1 - Legacy "globally active ticket" marker is gone (real regression, NOT a spec violation). The pre-existing UI showed a marker (triangle glyph) on whichever ticket was the user's globally active ticket (from ticket_activo_<pid>.json), independent of keyboard cursor position. In the new code, that marker is now driven solely by keyboard focus (focused_row in _row_text, widgets.py:395-420). _active is still computed per-ticket in _fetch() (widgets.py:317) but is never read by _render/_row_text/build_board_rows/the Row dict shape, it is genuinely dead code. Verdict: real UX regression, but NOT a spec violation. I read all 8 requirements and 16 scenarios in tui-ticket-dashboard/spec.md line by line; the only requirement that touches "active ticket" at all is Active Board Resolution, and its 3 scenarios are exclusively about which board is selected on mount, none of the 8 requirements or 16 scenarios describes a per-row visual marker for the globally active ticket. This loss is real, was honestly disclosed by apply (Deviation #2), and is worth a follow-up ticket, but it does not block this SDD change's archive since the spec never required it to be preserved.

- W2 - Graceful Degradation's "failed fetch" scenario is untestable end-to-end in production today (confirmed, not just apply's claim). I traced jira.fetch_subtasks (jira.py:119-142): it wraps its entire body in try/except Exception and returns [] on any HTTP-non-200 or exception, exactly like fetch_issue/fetch_comments. It never raises. TicketPanel._fetch()'s try/except Exception around fetch_subtasks(key) (widgets.py:341-346) can therefore never populate its failed set from a real network failure, that branch is dead code today. I checked what actually happens on a real failure: siblings.get(parent_key, []) returns [], so build_board_rows emits a normal (non-degraded) card with chips: []. Functionally this is graceful, no crash, move_sub is a no-op on a 0-chip card, target_ticket_id falls back to the parent key exactly as the degraded path does, but it is visually indistinguishable from a story that legitimately has zero subtasks, and skips the literal spec wording (flat single-row rendering with a "chips no disponibles" notice/degraded flag). The only test covering the literal degraded-flag contract (test_degraded_flag_when_parent_key_failed) calls build_board_rows directly with a synthetic failed set, bypassing the real _fetch() to fetch_subtasks wiring entirely. Not blocking: functionally equivalent, no crash, and this was an explicitly-scoped, honestly-disclosed tradeoff (jira.py changes restricted to the parent field per Scope point 1). Recommend a follow-up to jira.py's error contract (e.g. a distinguishable exception or sentinel) if the maintainer wants the literal degraded-card UX reachable.

- W3 - Could not independently reproduce a clean live-harness keyboard-nav pass; found a real, easily-reproducible Textual compositor crash instead. I wrote 4 independent throwaway App.run_test() scripts (not committed) attempting the requested final targeted pass on keyboard nav. Every attempt that mounted a real TicketPanel, even a bare mount with zero interaction, crashed inside Textual 8.2.8's compositor with "AttributeError: 'NoneType' object has no attribute 'render_strips'" during Screen._on_screen_resume/_refresh_layout. I isolated the trigger: a plain Widget subclass with the same compose() structure but without DEFAULT_CSS/can_focus=True/reactive attributes did NOT crash; a minimal reactive Static widget also did NOT crash. So the crash is specific to TicketPanel's combination of can_focus=True on a container Widget plus its focus/focus-within border-changing CSS, under this environment's Textual version, and it reproduces on every mount attempt in my session, not just "some pilot.pause() calls" as apply-progress's disclosure characterized it. This matches the exact error signature apply-progress already disclosed (corroborating apply did not fabricate it), but I was not able to get past it to independently execute my own scripted Up/Down/Left/Right/Enter assertions, the crash happens before any key press. Given design.md pre-emptively rejected a permanent Pilot harness citing this exact fragility class, and given the pure nav-logic functions underlying all keyboard behavior are solidly unit-tested (10/16 scenarios COMPLIANT above), I assess this as non-blocking for archive but flag it as a genuinely unresolved, unverified risk: whether this crash also manifests in a real terminal session (not just the headless run_test() driver) is unknown, neither apply nor verify had access to a real terminal in this environment. Recommend: a quick manual smoke test in a real terminal (press "t" to focus the ticket panel, then arrow around) before or shortly after this change ships, to confirm the real terminal driver doesn't hit the same code path.

**SUGGESTION**:

- Consider re-threading _active/active_tid through Row/build_board_rows in a follow-up (it would need a signature change, which was correctly avoided in this change per design's literal-interface constraint) to restore the legacy active-ticket marker as a visually distinct indicator alongside the new focus-based marker.
- Corrected scenario/requirement counts (8 requirements / 16 scenarios) differ from the count cited in this phase's launch brief (20 scenarios); likely a miscount upstream; downstream phases should use the actual spec.md file as authoritative.

### Assertion Quality
All 3 new/modified test files (test_jira_parent_field.py, test_ticket_panel_nav.py, test_board_switcher_filter.py) were scanned for banned trivial-assertion patterns (tautologies, ghost loops, orphan empty checks without a companion non-empty test, mock-to-assertion ratio).

**Assertion quality**: All assertions verify real behavior. No tautologies, no ghost loops, no smoke-test-only patterns. test_ticket_panel_nav.py's table-driven MoveSubTestCase asserts a distinct expected value per case (well-triangulated, no variance-free assertions). test_jira_parent_field.py mocks exactly httpx.post once per test against 1-2 real value assertions each (well under the 2x mock-heavy threshold).

### TDD Compliance
| Check | Result | Details |
|-------|--------|---------|
| TDD Evidence reported | Yes | Found in apply-progress (sdd/dashboard-story-switcher/apply-progress, id 282) |
| All tasks have tests | Yes (for testable pure functions) | jira.py parent field, widgets.py pure helpers, modals.py filter_boards; Textual widget wiring is standard-mode per design (no Pilot precedent) |
| RED confirmed (tests exist) | Yes | test_jira_parent_field.py, test_ticket_panel_nav.py, test_board_switcher_filter.py all exist and were independently re-run |
| GREEN confirmed (tests pass) | Yes | 32/32 focused + 6 subtests, 109/109 full suite, both independently re-executed this session |
| Triangulation adequate | Yes | MoveSubTestCase table-driven (6 cases), ResolveInitialBoardTestCase (4 cases incl. edge cases), BuildBoardRowsTestCase (6 cases) |
| Safety Net for modified files | Yes | Full 109-test suite (all pre-existing tests) passes clean after the change; test_ticket_panel_grouping.py's intentional retirement confirmed superseded by BuildBoardRowsTestCase |

**TDD Compliance**: 6/6 checks passed

---

### Test Layer Distribution
| Layer | Tests | Files | Tools |
|-------|-------|-------|-------|
| Unit | 32 (+6 subtests) | 3 (test_jira_parent_field.py, test_ticket_panel_nav.py, test_board_switcher_filter.py) | unittest + unittest.mock |
| Integration | 0 | 0 | No Textual Pilot harness exists in this repo (explicit design decision) |
| E2E | 0 | 0 | not installed |
| **Total** | **32 (+6 subtests)** | **3** | |

---

### Changed File Coverage
Coverage analysis skipped, no coverage tool configured for this project.

---

### Quality Metrics
**Linter**: Not available (no ruff/flake8 configured)
**Type Checker**: Not available (no mypy configured)

### Verdict
PASS WITH WARNINGS
0 CRITICAL, 3 WARNING (2 honestly-disclosed-by-apply, 1 newly-found-by-verify), 2 SUGGESTION. All core algorithmic logic is solidly unit-tested and 109/109 passing; the WARNINGs describe out-of-spec UX loss, an unreachable-in-production degradation branch, and an unresolved live-terminal-nav risk, none of which are spec violations or task-completion gaps, so none block archive.
