# TUI Ticket Dashboard Specification

## Purpose

Single-board story dashboard for the TUI ticket panel: pinned reopened tickets, story cards with sibling status chips, loose tickets, an on-demand board switcher, and 2D keyboard navigation.

## Requirements

### Requirement: Board Switcher Modal

The system MUST open a board-switcher modal on the `"b"` binding, live-filter its board list by case-insensitive substring as the user types, and let Up/Down move selection, Enter confirm, Esc cancel.

#### Scenario: Filter narrows the list

- GIVEN the modal is open showing all boards
- WHEN the user types a substring
- THEN only boards whose name contains that substring (case-insensitive) remain listed

#### Scenario: Enter switches the active board

- GIVEN a board is selected in the modal
- WHEN the user presses Enter
- THEN the panel's active board switches to the selected board and the modal closes

#### Scenario: Esc cancels without changing the board

- GIVEN the modal is open and the panel was showing board A
- WHEN the user presses Esc
- THEN the modal closes and the panel still shows board A

### Requirement: Active Board Resolution

On panel mount, the system MUST resolve the active board to the board of the currently active ticket (from `ticket_activo_<pid>.json`) if one exists, else the first board alphabetically. The system MUST NOT persist this choice across restarts.

#### Scenario: Active ticket determines initial board

- GIVEN `ticket_activo_<pid>.json` references a ticket belonging to board "API"
- WHEN the panel mounts
- THEN the active board is "API"

#### Scenario: No active ticket falls back to alphabetical

- GIVEN no active-ticket file exists
- WHEN the panel mounts
- THEN the active board is the first board name alphabetically

#### Scenario: Board choice is not persisted

- GIVEN the user switched to board "Web" via the modal
- WHEN the app restarts
- THEN the initial board resolution runs again from scratch, ignoring the prior session's choice

### Requirement: Story Cards with Sibling Chips

The system MUST render each unique parent story as one card showing all its sibling sub-tasks as inline status chips (done/current/todo/blocked), fetching subtasks at most once per unique parent per refresh.

#### Scenario: Siblings render as chips

- GIVEN three sub-tasks share the same parent story
- WHEN the active board is rendered
- THEN one card appears for that story with three chips, each reflecting its sibling's real Jira status

#### Scenario: Dedup limits fetch calls

- GIVEN two of the active board's tickets share the same parent
- WHEN the panel fetches data
- THEN `fetch_subtasks` is called exactly once for that parent

### Requirement: Pinned Reopened Section

The system MUST render reopened tickets (`_bucket == "reabiertos"`) in a separate section always visible above the story cards, and MUST NOT duplicate a reopened ticket inside a story card even if it is also a sub-task.

#### Scenario: Reopened ticket appears only once

- GIVEN a reopened ticket is also a sub-task of a story shown on the active board
- WHEN the panel renders
- THEN the ticket appears in the pinned reopened section and does not appear as a chip in its parent's card

### Requirement: 2D Keyboard Navigation

Up/Down MUST move a single linear focus index across [reopened rows, story cards, loose ticket rows]. Left/Right MUST move a secondary focus index across the focused card's chips only, and MUST be a no-op on non-card rows.

#### Scenario: Up/Down crosses row types

- GIVEN focus is on the last reopened row
- WHEN the user presses Down
- THEN focus moves to the first story card

#### Scenario: Left/Right is a no-op outside cards

- GIVEN focus is on a loose ticket row
- WHEN the user presses Right
- THEN focus does not change

### Requirement: Enter Activation Semantics

When the focused row is a story card, Enter MUST act on whichever chip currently holds sub-focus. On non-card rows (reopened, loose), Enter MUST act on that row directly.

#### Scenario: Enter on a card targets the sub-focused chip

- GIVEN a story card is focused with its second chip sub-focused
- WHEN the user presses Enter
- THEN the ticket represented by that second chip is opened via `TicketSelected`

#### Scenario: Enter on a reopened row opens that ticket

- GIVEN focus is on a reopened row
- WHEN the user presses Enter
- THEN that ticket is opened via `TicketSelected`

### Requirement: Graceful Degradation

An empty active board MUST show a plain message with no crash and no stale data from a prior board. A `fetch_subtasks` failure for one parent MUST degrade only that card to a flat single-row rendering (ticket id + summary, no chips), without breaking the rest of the panel.

#### Scenario: Empty board shows a message

- GIVEN the active board has no assigned tickets
- WHEN the panel renders
- THEN a message such as "Sin tickets asignados en <BOARD>" is shown and no prior board's rows remain

#### Scenario: One failed subtask fetch degrades only its card

- GIVEN `fetch_subtasks` fails for one parent story on a board with other stories
- WHEN the panel renders
- THEN that story renders as a flat row without chips, and all other cards render normally

### Requirement: Non-Regression of Existing Contracts

The `TicketSelected` message contract, the `@work(thread=True, exclusive=True)` fetch pattern, and the 4-minute `set_interval` auto-refresh MUST continue to function unchanged.

#### Scenario: Auto-refresh still runs

- GIVEN the panel has been mounted for 4 minutes
- WHEN the refresh interval fires
- THEN ticket data is re-fetched using the same threaded, exclusive `@work` pattern as before this change
