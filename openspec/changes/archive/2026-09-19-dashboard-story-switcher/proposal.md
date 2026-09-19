# Proposal: Dashboard Story Switcher

## Intent

The TUI ticket panel shows a flat, board-grouped list: every board at once, no hierarchy, no way to jump boards. A sub-task's siblings are invisible unless the user runs `ctx resume` and answers a one-shot prompt. Users lose the "where am I in this story" picture and must scroll past unrelated boards. This change turns the panel into a single-board story dashboard with an on-demand board switcher, surfacing hierarchy data the Jira layer already fetches.

## Scope

### In Scope
- `fetch_my_issues` requests and parses `parent` (same shape `fetch_issue` uses).
- `TicketPanel` renders one active board: pinned reopened strip, story cards with sibling status chips, loose tickets.
- 2D keyboard nav: Up/Down across rows/cards, Left/Right across a focused card's chips, Enter opens the focused item.
- `BoardSwitcherModal` — `Input` + live-filtered `OptionList` of boards with ticket/reopened counts; Enter switches, Esc cancels.
- `"b"` binding on `MainScreen` (verified free; consistent with existing `t`/`p`/`s`).
- Per-board dedup: 1 `fetch_subtasks` call per unique parent, in `TicketPanel._fetch()`.

### Out of Scope
- Fuzzy/typo-tolerant matching (see Approach), sibling assignees, board pinning/reordering, cross-board aggregate views, `ctx resume` prompt changes, `_group_by_board`'s board-prefix derivation.

## Capabilities

### New Capabilities
- `tui-ticket-dashboard`: single-board story dashboard — reopened strip, story cards with sibling chips, 2D nav, board switching.

### Modified Capabilities
- None. `jira-resume-context` behavior is untouched; the `parent` field addition is additive.

## Approach

Drop `ListView` (one linear index cannot express chip sub-focus) and adopt `ProjectScreen`'s `_cursor`/`watch__cursor`/`on_key` reactive-index pattern with two indices (row, chip); `can_focus` becomes `True`. Keep the existing `@work(thread=True)` fetch, `set_interval` refresh and `TicketSelected` message contract. `BoardSwitcherModal` copies `SelectModal`'s structure plus `Input.Changed` → `clear_options()`/`add_options()`.

**Filtering decision: case-insensitive substring, stdlib only.** A personal board list is single-digit to low-tens; fuzzy matching pays off at hundreds of items. A third-party dependency is rejected per this repo's standing rule (DEC-080). If typo tolerance is ever needed, stdlib `difflib.get_close_matches` is the escape hatch — no dependency, ever.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `aicli/services/jira.py` | Modified | `parent` in fields list + parsing (~8 lines) |
| `aicli/tui/widgets.py` | Modified | Render/selection core replaced (~280 add / ~150 del) |
| `aicli/tui/modals.py` | New | `BoardSwitcherModal` (~120 lines) |
| `aicli/tui/screens.py` | Modified | `"b"` binding + dismiss wiring (~15 lines) |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Exceeds 400-line review budget (~590 est.) | High | Split: Slice A (parent field + modal + `"b"` + single-board filter, `ListView` kept), Slice B (cards/chips/2D nav) |
| `can_focus: False → True` breaks focus cycle | Med | Focus-cycle check in design; `t`/`focus_tickets` still entry point |
| `M` unique parents → `1+M` API calls per refresh | Med | Dedup per board; only active board fetched |
| MainScreen `h`/`l` vs. card nav | Low | Card nav uses arrow keys only |

## Rollback Plan

Pure code change: no schema, no migration, no new dependency, no config. Revert the commit(s); `fetch_my_issues` returns to 3 fields and `TicketPanel` to its `ListView` render. No persisted state is written, so no cleanup is required.

## Dependencies

- None. Existing `textual==8.2.8` and current `jira.py` endpoints suffice.

## Success Criteria

- [ ] Panel shows exactly one board; `"b"` switches it, Esc cancels with no change.
- [ ] Sub-task tickets render under their parent story with sibling chips; loose tickets stay listed.
- [ ] Reopened tickets always pinned above, never mixed into stories.
- [ ] Up/Down/Left/Right/Enter behave as validated in the mockups.
- [ ] `requirements.txt` unchanged.
