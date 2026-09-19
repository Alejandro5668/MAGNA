# Exploration: dashboard-story-switcher (board-switcher + story/sibling hierarchy dashboard)

## Current State (verified file:line)

1. **`aicli/services/jira.py`** — `fetch_my_issues()` (line 189-232) requests `fields: ["summary","status","priority"]` at line 201, no `"parent"`. `fetch_issue()` (78-116) and `fetch_subtasks()` (119-142) confirmed exactly as `state.yaml` described, including that `fetch_subtasks` returns no assignee per sibling. **Change needed**: add `"parent"` to the fields list (line 201) + parse it the same way `fetch_issue` already does (lines 95-101).

2. **`aicli/tui/widgets.py` `TicketPanel`** (267 lines, current post-session state) — `_fetch()` (121-157) is `@work(thread=True, exclusive=True)`; `_group_by_board()` (165-184) groups a flat list with synthetic header rows; `_populate()` (186-207) preserves selection by ticket id. All selection/nav is `ListView`-driven (single linear index). **Critical finding**: `ListView`/`OptionList` only expose one linear `highlighted` index (verified in Textual's real `_option_list.py`) — they cannot express the validated UX's Left/Right sub-focus across sibling chips. The new widget must drop `ListView` and use bespoke rendering + two reactive indices, following the `ProjectScreen._cursor`/`watch__cursor`/`on_key` pattern in `aicli/tui/screens.py` (lines 976, 1067-1092) — that pattern is directly reusable and is this codebase's real precedent for compound custom key nav. `can_focus` (currently `False`, verified line 46) would need to become `True` since there'd be no focusable `ListView` child to bubble keys up.

3. **`aicli/tui/modals.py`** (601 lines) — confirmed inventory: `HelpScreen`, `InputModal`, `TextAreaModal`, `SelectModal`, `ConfirmModal`, `JiraCardModal`, all `ModalScreen[T]` + `dismiss()`. `SelectModal` (291-366) exists exactly as claimed but is **static, non-filterable** (no `Input`, options built once). A new modal is needed, modeled directly on `SelectModal`'s structure.

4. **Textual live-filter mechanism** — verified against real installed `textual==8.2.8` source: `Input.Changed` (`_input.py` 286-307, handled via `on_input_changed`) + `OptionList.clear_options()`/`add_options()` (`_option_list.py` 326/362) is the real, idiomatic filter-as-you-type mechanism. No fuzzy-match library is installed anywhere (`rapidfuzz`/`thefuzz`/`difflib` all absent from `requirements.txt` and the whole tree) — flagged as an open decision for propose (stdlib substring match vs. new dependency).

5. **Fetch cost model** — confirmed `1 + M` (M = unique parent keys, deduped). No existing dedup helper exists. Given jira.py's convention (every function = exactly one REST call, composition always happens caller-side — see `_resume_jira_context` in `screens.py` 243-270 and `TicketPanel._fetch`+`_group_by_board` doing their own composition/grouping), the dedup+aggregation logic belongs in `widgets.py`'s `_fetch()`, not as a new `fetch_my_issues_with_stories()` in `jira.py` (would break the established 1:1-endpoint convention and be premature abstraction for one caller).

6. **Reopened bucket** — `_bucket` (widgets.py line 141, sourced from jira.py 208-227) is fully independent of the `parent` field; confirmed compatible, no changes needed.

7. **Focus/keyboard model** — confirmed reusable `ProjectScreen` reactive-index pattern (see #2); no native Textual focus-chain mechanism is used anywhere in this codebase for compound nav, so it's not the right fit either. The global `"b"` binding location in `MainScreen`/`screens.py` wasn't located this pass (small follow-up for design, not a blocker).

## Recommended Scope Split
- **jira.py**: one small field-list + parsing change.
- **widgets.py**: near-full rewrite of `TicketPanel`'s render/selection core (drop `ListView`, dual reactive-index nav), reusing fetch/refresh/message scaffolding.
- **modals.py**: one new `BoardSwitcherModal`, modeled on `SelectModal` + `Input.Changed` filtering.
- **screens.py**: small `"b"` binding wiring (location TBD in design).
- No new third-party dependency is strictly required.

## Risks
- TicketPanel change is a near-full replacement of the render/selection core, not an incremental patch, despite `state.yaml`'s "reuse scaffolding" framing (scaffolding IS reusable — fetch/refresh/message contract — but not render/selection).
- Fuzzy-match approach (stdlib vs. new dependency) is unresolved — needs an explicit propose-phase decision.
- `"b"` global binding's exact home in `screens.py` not yet located.
- `can_focus: False → True` on the TicketPanel replacement should get a quick focus-cycle sanity check in design/apply.

## Ready for Proposal

Yes.
