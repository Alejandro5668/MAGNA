# Tasks: Dashboard Story Switcher

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~640 source (design) + ~150-250 new TDD test files ≈ 750-850 total |
| 400-line budget risk | High |
| Chained PRs recommended | No |
| Suggested split | Single PR — `size:exception` already accepted (state.yaml, FINAL) |
| Delivery strategy | single-pr |
| Chain strategy | size-exception |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: High

Design's ~640 estimate covers only the 4 production files; it does not include the 3 new TDD test files this breakdown requires (`test_jira_parent_field.py`, `test_ticket_panel_nav.py`, `test_board_switcher_filter.py`). Real total is likely 750-850 changed lines. This does not invalidate the accepted exception — the exception was granted at the whole-PR level, and there is no new evidence it needs to be reopened, only a magnitude correction.

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Full dashboard story switcher (jira.py + widgets.py + modals.py + screens.py) | PR 1 | `.venv\Scripts\python.exe -m pytest tests/test_jira_parent_field.py tests/test_ticket_panel_nav.py tests/test_board_switcher_filter.py -v` | Manual scripted pass: launch TUI, exercise `t`/`b`/`g`/`G`, arrow nav, Enter on chip (design rejects a `Pilot` harness — no precedent) | Revert the single commit; no schema/migration/persisted state to unwind |

## Requirement Mapping (by phase)

| Phase | Spec requirement(s) |
|---|---|
| 1 | Story Cards with Sibling Chips (parent data prerequisite) |
| 2 | Active Board Resolution, Story Cards w/ Sibling Chips, Pinned Reopened, 2D Nav, Enter Activation, Graceful Degradation |
| 3 | All 8 requirements (render/nav/fetch/degradation core) |
| 4 | Board Switcher Modal |
| 5 | Board Switcher Modal (binding), 2D Nav (`g`/`G` fix), Non-Regression (`t` fix) |
| 6 | Non-Regression of Existing Contracts |

## Phase 1: jira.py — parent field

- [x] 1.1 RED: `tests/test_jira_parent_field.py` — `fetch_my_issues` parses `parent` present/absent/malformed (`@patch("httpx.post")`)
- [x] 1.2 GREEN: append `"parent"` to fields list (jira.py:201); parse each item's parent the same way `fetch_issue` does (jira.py:95-101)

## Phase 2: Pure helpers — widgets.py module-level (TDD)

- [x] 2.1 RED `tests/test_ticket_panel_nav.py`: `unique_parent_keys` dedup
- [x] 2.2 GREEN: implement `unique_parent_keys`
- [x] 2.3 RED: `resolve_initial_board` — active ticket present / absent / no tickets
- [x] 2.4 GREEN: implement `resolve_initial_board`
- [x] 2.5 RED: `build_board_rows` — reopened→cards→loose order, reopened ticket never duplicated as a chip, `degraded` flag, empty-board case
- [x] 2.6 GREEN: implement `build_board_rows` + `Row` dict shape
- [x] 2.7 RED: `move_focus`/`move_sub`/`target_ticket_id` — clamped no-wrap, `move_sub` no-op on non-card rows (table-driven)
- [x] 2.8 GREEN: implement `move_focus`, `move_sub`, `target_ticket_id`
- [x] 2.9 Retire `tests/test_ticket_panel_grouping.py` — it tests `_group_by_board`, which this design retires. Delete the file; its coverage (board grouping/ordering) is superseded by 2.5/2.6's `build_board_rows` tests. Do not leave it silently broken.

## Phase 3: TicketPanel core rewrite (widgets.py)

- [x] 3.1 `can_focus = True`; CSS `#tp-list` → `#tp-body`/`#tp-rows`; add `TicketPanel:focus` rule; single `Static` inside `VerticalScroll(can_focus=False)`
- [x] 3.2 Add `_focus: reactive[int]`, `_sub: reactive[int]`, plain `dict[str,int]` chip-index memory; watchers trigger `_render()`
- [x] 3.3 Rewrite `_fetch()`: `fetch_my_issues()` → `unique_parent_keys` → `resolve_initial_board` (first mount only, never persisted) → per-parent `fetch_subtasks` wrapped in `try/except` into a `failed` set → `call_from_thread(_populate, ...)`
- [x] 3.4 Rewrite `_populate()`: `build_board_rows(...)` → `self._rows` → `_render()`
- [x] 3.5 `_render()`: build one `Text` from `self._rows` reflecting `_focus`/`_sub`; `Static.update()`
- [x] 3.6 Scroll-to-focus: compute focused row's line offset during render; `container.scroll_to(y=..., animate=False)`
- [x] 3.7 Add `board_options()` and `set_board(board)` methods (clears rows, re-`_fetch()`)
- [x] 3.8 `on_key`: up/down → `move_focus`; left/right → `move_sub`; enter → `TicketSelected(target_ticket_id(...))`; `r` → `_fetch()` unchanged
- [x] 3.9 Wire empty-board message end-to-end: no stale rows from a prior board remain when the active board has 0 tickets

## Phase 4: BoardSwitcherModal (modals.py)

- [x] 4.1 RED `tests/test_board_switcher_filter.py`: `filter_boards` case-insensitive substring
- [x] 4.2 GREEN: implement `filter_boards`
- [x] 4.3 Add `BoardSwitcherModal(ModalScreen[str|None])` modeled on `SelectModal` (modals.py:291) + an `Input`; `on_input_changed` → `clear_options()`/`add_options()`; `dismiss(board_key)` / `dismiss(None)` on Esc
- [x] 4.4 Add 3 `_HELP_ROWS` entries (modals.py:31-45): `"b"`, `"←/→"`, Enter-on-chip

## Phase 5: MainScreen wiring (screens.py)

- [x] 5.1 Add `Binding("b", "board", show=False)` to `BINDINGS` (~line 1394)
- [x] 5.2 `action_board` → `@work async _worker_board`: `push_screen_wait(BoardSwitcherModal(panel.board_options(), current))` → `TicketPanel.set_board(board)`
- [x] 5.3 Fix `action_focus_tickets` (screens.py:1546-1550): retarget from `query_one("#tp-list", ListView)` to the `TicketPanel` widget itself
- [x] 5.4 Fix `action_jump_top`/`action_jump_bottom` (screens.py:1532-1544): add a `TicketPanel` branch — `g` focuses first row, `G` focuses last row

## Phase 6: Integration verification

- [x] 6.1 Run `.venv\Scripts\python.exe -m pytest` (full suite) — confirm no regression, `test_ticket_panel_grouping.py` absence is intentional. 109/109 passed excluding `tests/test_commands.py`, a pre-existing (pre-dates this change, confirmed via `git stash`) broken legacy smoke script unrelated to this change that crashes pytest collection via `sys.exit(1)` at import time.
- [x] 6.2 Manual scripted pass — no live terminal available in this environment; used a throwaway (not committed) Textual `run_test()` harness in scratchpad to exercise `can_focus` False→True, `focus_first`/`focus_last` (`g`/`G`), arrow nav, chip sub-focus clamping, Enter-on-chip targeting, `BoardSwitcherModal` filter/Enter/Esc end-to-end against a real mounted app. Found and fixed one real bug (Enter with no highlighted option after filtering hung `push_screen_wait`). All asserted behavior passed. See apply-progress for full detail, including one unrelated Textual compositor artifact observed under the harness — recommend a real interactive pass before merging.
