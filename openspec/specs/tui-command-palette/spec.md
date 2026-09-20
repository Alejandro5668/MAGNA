# TUI Command Palette Specification

## Purpose

Single filterable entry point (`CommandPaletteModal`) that merges the 7 task
commands and every former `SettingsScreen` action (credentials, Gemini test,
team rules, logs) into one flat, searchable catalog opened with `/`, while
`MainScreen` gives the ticket board the full screen with no sidebar.

## Requirements

### Requirement: Full-Width Ticket Panel

`MainScreen.compose` MUST NOT render a `#left` sidebar. `TicketPanel` MUST be
the sole child of `#body` and MUST receive focus on mount.

#### Scenario: Board fills the screen
- GIVEN `MainScreen` mounts
- WHEN compose runs
- THEN no sidebar container exists and `TicketPanel` occupies the full width of `#body`, focused

### Requirement: Command Palette Invocation

The system MUST open `CommandPaletteModal` on the `/` binding, built on the
`Input` + `OptionList` shell already proven by `BoardSwitcherModal`, showing
the full catalog with the `Input` focused. Escape MUST dismiss the modal with
no effect on catalog state or app state.

#### Scenario: Opening the palette shows the full catalog
- GIVEN `MainScreen` is active
- WHEN the user presses `/`
- THEN `CommandPaletteModal` opens listing all 16 catalog entries with the filter `Input` focused

#### Scenario: Escape cancels without effect
- GIVEN the palette is open, filtered or not
- WHEN the user presses Escape
- THEN the modal closes, no command runs, no setting changes, and `MainScreen` state is unchanged

### Requirement: Live Substring Filter

The palette MUST filter by case-insensitive substring match over each entry's
name and description combined, re-evaluated on every `Input.Changed` (same
shape as `filter_boards`). WHEN no entry matches, the list MUST show exactly
one non-actionable "Sin resultados" row.

#### Scenario: Filter narrows the catalog
- GIVEN the palette is open with the full catalog
- WHEN the user types "gemini"
- THEN only entries whose name or description contains "gemini" remain, including `GEMINI_API_KEY` and "Probar conexión Gemini"

#### Scenario: No match shows a placeholder
- GIVEN the palette is open
- WHEN the user types a substring matching no entry
- THEN the list shows exactly one "Sin resultados" row and Enter on it has no effect

### Requirement: Flat Catalog Content

`_PALETTE_ENTRIES` MUST contain exactly: 7 commands (`file`, `archive`,
`task`, `sync`, `resume`, `claude`, `status`); 5 credentials
(`ANTHROPIC_API_KEY`, `JIRA_URL`, `JIRA_EMAIL`, `JIRA_TOKEN`,
`GEMINI_API_KEY`); and 4 actions ("Probar conexión Gemini", "Agregar regla de
equipo", "Eliminar regla de equipo…", "Ver logs") — 16 entries total. Each row
MUST show a category tag, name, and description. Each credential row MUST
show the ✓/✗ configured badge reflecting live env-var state.

#### Scenario: Credential badge reflects configuration
- GIVEN `JIRA_TOKEN` is unset and `ANTHROPIC_API_KEY` is set
- WHEN the palette renders
- THEN the `JIRA_TOKEN` row shows ✗ and the `ANTHROPIC_API_KEY` row shows ✓

### Requirement: Command Dispatch

Dismissing the palette with `("cmd", id)` MUST invoke the existing
`action_cmd(id)` unchanged, driving the existing
`CommandScreen`/`CommandOutputScreen` flow. `settings` MUST NOT be a `cmd`
entry.

#### Scenario: Selecting a command launches it
- GIVEN the palette is open
- WHEN the user selects the "resume" entry
- THEN the palette closes and `action_cmd("resume")` runs the existing resume flow

### Requirement: Setting Dispatch

Dismissing the palette with `("setting", id)` MUST invoke a new
`MainScreen._worker_setting(id)` that reuses `_save_env_var`, `InputModal`,
`ConfirmModal`, `SelectModal`, and `LogScreen` unchanged, covering every
action the former `SettingsScreen._worker_action` covered.

#### Scenario: Selecting a credential saves it
- GIVEN the user selects the `JIRA_TOKEN` credential entry
- WHEN `InputModal` is submitted with a non-empty value
- THEN `_save_env_var("JIRA_TOKEN", value)` persists it and the badge shows ✓ on next palette open

#### Scenario: Adding a team rule
- GIVEN the user selects "Agregar regla de equipo"
- WHEN `InputModal` returns a valid `.md` path
- THEN the file is copied into the rules directory and a confirmation is shown

#### Scenario: Deleting a team rule
- GIVEN the user selects "Eliminar regla de equipo…"
- WHEN `SelectModal` returns a rule filename and `ConfirmModal` is confirmed
- THEN that rule file is removed from the rules directory

#### Scenario: Viewing logs
- GIVEN the user selects "Ver logs"
- WHEN the selection is dismissed
- THEN `LogScreen` opens showing the log content, unchanged from prior behavior

### Requirement: Description Lookup Sourced From Catalog

`_cmd_desc(command)` MUST resolve a command's description from
`_PALETTE_ENTRIES` instead of `_MENU`, preserving its existing signature and callers.

#### Scenario: CommandScreen still shows the right description
- GIVEN `_MENU` no longer exists
- WHEN `CommandScreen` is opened for "sync"
- THEN it displays the same description text `_cmd_desc("sync")` returned before this change

### Requirement: Settings Screen and Menu Removal

`SettingsScreen`, `_MENU`, `_menu_option`, and `_cfg_option` as a standalone
settings-list builder MUST NOT exist in the codebase after this change.

#### Scenario: No dangling references
- GIVEN the change is applied
- WHEN the codebase is searched for `SettingsScreen`, `_MENU`, or `_menu_option`
- THEN no matches are found outside archived history

### Requirement: Binding Cleanup

`MainScreen.BINDINGS` MUST NOT include `1`–`7`, `s`, `h`, `l`, or `t`. It MUST
retain `g`, `G`, `b`, `p`, `q`, `?` without their dead `OptionList`/`ListView`
branches, and MUST add `/` bound to opening the palette. `_HELP_ROWS` MUST
list only bindings that still exist.

#### Scenario: Removed bindings are inert
- GIVEN `MainScreen` is active
- WHEN the user presses `3` or `s`
- THEN no command runs and no screen changes

#### Scenario: Retained bindings still work
- GIVEN `MainScreen` is active with tickets rendered
- WHEN the user presses `g`, `G`, `b`, `p`, or `?`
- THEN each performs its existing behavior unchanged (jump top/bottom, board switcher, project switcher, help)

## Non-Requirements

Explicitly out of scope for this capability, per the approved proposal:
- Inline editing of a setting's value inside a palette row.
- A "recientes" (recently used) section.
- Fuzzy matching — substring match only.
- One palette row per rule file instead of a single delete-and-select entry.
- Fixing `tests/test_commands.py`'s pre-existing `ImportError` failures.
