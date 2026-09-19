# Design: Dashboard Story Switcher

## Technical Approach

`TicketPanel` stops being a `ListView` host and becomes a self-rendering focusable widget: one Rich `Text` painted into a single `Static` inside a non-focusable `VerticalScroll`, driven by two reactive indices — exactly `ProjectScreen._cursor`/`watch__cursor`/`on_key` (screens.py:976, 1067-1092), this repo's only precedent for compound key nav. Fetch scaffolding (`@work(thread=True, exclusive=True)`, `set_interval`, `TicketSelected`) is untouched; dedup/aggregation is added inside `_fetch()`. All ordering/nav/filter logic lands in module-level pure functions so it is unit-testable without mounting Textual.

## Architecture Decisions

| Decision | Choice | Rejected | Rationale |
|---|---|---|---|
| Row rendering | One `Text` → one `Static` in `VerticalScroll(can_focus=False)` | `ListView`; one `Static` per row | `ListView` cannot express chip sub-focus (exploration #2). Per-row widgets need mount/unmount diffing; a single `Text` is the `ProjectScreen` precedent and re-render is cheap (tens of lines). `can_focus=False` is a verified ctor arg (`containers.py:83`), so the container never steals focus from `TicketPanel`. |
| Scroll-to-focus | `container.scroll_to(y=..., animate=False)` with the focused row's line offset computed during render | `scroll_visible()` on a row widget | No per-row widget exists; `scroll_to` is verified at `widget.py:2859`. |
| Focus state | `_focus: reactive[int]` + `_sub: reactive[int]`, plus a plain `dict[str, int]` remembering each card's chip index | Single tuple reactive; dict reactive | Two ints give two clean watchers; a mutated dict does not re-trigger `watch_`. The dict preserves chip position when Up/Down leaves and returns to a card. |
| Enter semantics | Every row exposes a `chips` list; non-card rows have exactly one chip | Special-casing card vs. row at keypress time | Makes "Enter targets the sub-focused chip" literally true everywhere (state.yaml) while satisfying the spec's row behaviour, with no branch in the handler. |
| Aggregation site | Dedup + `fetch_subtasks` fan-out in `widgets.py::_fetch()` | New `fetch_my_issues_with_stories()` in `jira.py` | jira.py is strictly 1 function = 1 REST call; composition is caller-side (exploration #5). |
| Subtask failure | `try/except` **per parent key**, marking that row `degraded=True` | One `try` around the fan-out | Spec: one failure degrades one card to a flat row, not the panel. |
| Board filter | `q.lower() in name.lower()` | `rapidfuzz` / `difflib` | Single-digit board list; no new dependency (DEC-080). |

## Data Flow

    b ─→ MainScreen.action_board ─→ _worker_board (@work async)
           │                             │ push_screen_wait(BoardSwitcherModal)
           │                             ↓ board key | None
           └────────────────→ TicketPanel.set_board() ─→ _fetch()

    _fetch (thread)  fetch_my_issues()            → flat[] (+_board,_bucket,_active,_rounds)
                     resolve_initial_board(...)   → active board (once, never persisted)
                     fetch_subtasks(k) per unique parent of the ACTIVE board only
                     call_from_thread(_populate, rows, board_counts)
    _populate → build_board_rows() → self._rows → _render() → Static.update()

## File Changes

| File | Action | Description |
|---|---|---|
| `aicli/services/jira.py` | Modify | `"parent"` appended to the `fields` list (line 201); parse into each item exactly as `fetch_issue` does (lines 95-101): `{"key", "summary"}` or `None`. |
| `aicli/tui/widgets.py` | Modify | `TicketPanel` render/selection core replaced; `_group_by_board` retired; new pure helpers; `can_focus = True`; CSS `#tp-list` → `#tp-body`/`#tp-rows` plus a `TicketPanel:focus` rule. |
| `aicli/tui/modals.py` | Modify | New `BoardSwitcherModal`; three new `_HELP_ROWS` entries (`b`, `←/→`, Enter-on-chip). |
| `aicli/tui/screens.py` | Modify | `Binding("b", "board", show=False)`; `action_board` → `@work async _worker_board`; `action_focus_tickets` targets `TicketPanel` instead of `#tp-list`; `action_jump_top`/`jump_bottom` gain a `TicketPanel` branch (they currently only know `OptionList`/`ListView`). |

## Interfaces / Contracts

```python
# widgets.py — row model (discriminated dict, same spirit as the old "_header" row)
Row = dict  # {"_kind": "reopened"|"card"|"loose", "label": str,
            #  "chips": list[dict],        # each: {"id","summary","status","_state"}
            #  "parent": dict | None, "degraded": bool}

def unique_parent_keys(tickets: list[dict]) -> list[str]: ...
def resolve_initial_board(tickets: list[dict], active_tid: str | None) -> str | None: ...
def build_board_rows(tickets, siblings: dict[str, list[dict]],
                     failed: set[str]) -> list[Row]: ...          # reopened → cards → loose
def move_focus(rows, index: int, delta: int) -> int: ...          # clamped, no wrap
def move_sub(rows, index: int, sub: int, delta: int) -> int: ...  # clamped within row's chips
def target_ticket_id(rows, index: int, sub: int) -> str | None: ...

class TicketPanel(Widget):
    can_focus = True
    def board_options(self) -> list[tuple[str, int, int]]: ...    # (board, total, reopened)
    def set_board(self, board: str) -> None: ...                  # sets board, clears rows, _fetch()

# modals.py
def filter_boards(options: list[tuple[str, int, int]], query: str) -> list[tuple[str, int, int]]

class BoardSwitcherModal(ModalScreen[str | None]):
    """SelectModal's structure + an Input; on_input_changed → OptionList
    .clear_options()/.add_options(). dismiss(board_key) | dismiss(None) on Esc."""
    def __init__(self, options: list[tuple[str, int, int]], current: str | None) -> None: ...
```

`on_key` maps `up`/`down` → `move_focus`, `left`/`right` → `move_sub`, `enter` → `TicketSelected(target_ticket_id(...))`, `r` → `_fetch()` (unchanged). Reopened ticket ids are excluded from chip lists so a ticket never renders twice.

## Testing Strategy

No Textual `Pilot`/`run_test` precedent exists anywhere in `tests/`; the convention is `unittest` + `unittest.mock.patch` (`test_jira_comments.py`) and direct pure-logic calls (`test_ticket_panel_grouping.py`).

| Layer | What | Approach |
|---|---|---|
| Unit | `parent` parsing in `fetch_my_issues` (present / absent / malformed) | `@patch("httpx.post")`, `tests/test_jira_parent_field.py` |
| Unit | `unique_parent_keys` dedup, `resolve_initial_board` (active ticket / fallback / no tickets) | direct calls |
| Unit | `build_board_rows`: ordering, reopened-never-a-chip, `degraded` flag, empty board | direct calls |
| Unit | `move_focus` / `move_sub` / `target_ticket_id` clamping + no-op on non-card rows | direct calls, table-driven |
| Unit | `filter_boards` case-insensitive substring | direct calls |
| Manual | Focus cycle after `can_focus: False → True`, `t`/`b`/`g`/`G`, scroll-to-focus | one scripted manual pass in apply |

Introducing a `Pilot` smoke test is rejected: it would be the repo's first async test harness for one keypress path already covered by the pure-transition tests, against this project's "no premature abstraction" rule. Escape hatch if regressions appear: `unittest.IsolatedAsyncioTestCase` + `App.run_test()`, no new dependency.

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary. The only I/O change is one extra field on an existing authenticated Jira request.

## Migration / Rollout

No migration. Pure code change: no schema, no migration, no new dependency, no config, no persisted state (board choice is in-memory only). Rollback = revert the commit.

**Line forecast (informational; `size:exception` already accepted):** jira.py ~9, widgets.py ~330 add / ~150 del, modals.py ~128, screens.py ~22 → **~640 changed lines**, above the earlier ~590 estimate because of the `jump_top`/`jump_bottom`/`focus_tickets` and help-row follow-ons. Single PR, per `delivery_strategy: single-pr`.

## Open Questions

- None blocking.
