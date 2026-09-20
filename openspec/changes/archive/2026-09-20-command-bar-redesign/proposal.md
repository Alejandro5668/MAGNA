# Proposal: Command Bar Redesign

## Intent

MAGNA's TUI splits one mental model across two systems: a fixed 54-column `_MENU` sidebar (8 commands in 4 collapsibles) and a separate `SettingsScreen` (3 more lists). The user must first know *which* system owns what, and the ticket board — the screen's actual subject — lives in the leftover width. Replace both with a single filterable command palette and give the board the full screen.

## Scope

### In Scope

- Remove `#left` from `MainScreen.compose`; `TicketPanel` becomes the sole child of `#body` (full width, focused on mount). No change to `widgets.py`.
- New `CommandPaletteModal` in `modals.py`, built on `BoardSwitcherModal`'s `Input` + `OptionList` + `on_input_changed` + manual up/down/enter routing. Opened with `/` (visible in Footer).
- Flat catalog `_PALETTE_ENTRIES` replaces `_MENU`: 8 commands + 5 credentials (keeping the live ✓/✗ badge from `_cfg_option`) + "Probar conexión Gemini" + "Agregar regla de equipo" + "Eliminar regla de equipo…" + "Ver logs". Row = category tag + name + description.
- Case-insensitive substring filter over `name + description` (same shape as `filter_boards`). No match → single "Sin resultados" row.
- `_cmd_desc` survives, now sourced from `_PALETTE_ENTRIES` (`CommandScreen`/`CommandOutputScreen` keep working untouched).
- Delete `SettingsScreen`; port its `_worker_action` branches into `MainScreen._worker_setting`, reusing `_save_env_var`, `InputModal`, `ConfirmModal`, `SelectModal`, `LogScreen` unchanged.
- Palette dismisses `("cmd", id)` → existing `action_cmd`, or `("setting", id)` → `_worker_setting`.
- Binding cleanup: drop `1`–`7`, `s`, `h`, `l`, `t`. Keep `g`/`G` (drop their dead `OptionList`/`ListView` branches), `b`, `p`, `q`, `?`. Update `_HELP_ROWS`.

### Out of Scope — decided, not open questions

- **Inline editing inside the palette.** `OptionList` cannot host a live `Input`; it would force a `ListView`/`ListItem` migration with zero precedent in this repo plus a new focus/Escape state machine. It does not serve the goal. Enter on a setting opens the existing `InputModal`.
- **"Recientes".** Requires a new persisted `~/.mycontext/*.json` to write, cap, migrate and test; over a ~16-entry catalog two keystrokes already filter. Revisit only if the catalog grows materially.
- **Fuzzy search.** New dependency, no benefit over substring here ("gemini" already matches `GEMINI_API_KEY`).
- **One palette row per rule file.** A single "Eliminar regla…" entry opening `SelectModal` keeps the catalog static and small.
- **`tests/test_commands.py`.** Its 4 failures are pre-existing `ImportError`s from an earlier `app.py` split. Not fixed here; this change must not add new failures.

## Capabilities

### New Capabilities

- `tui-command-palette`: single filterable entry point that merges command launching and settings actions, replacing the sidebar menu and the settings screen.

### Modified Capabilities

- None. `tui-ticket-dashboard` requirements are unchanged; the panel only gains width.

## Approach

Exploration Approach 1 (full flatten). Reuse over invention: the palette shell is `BoardSwitcherModal`'s proven pattern, execution is the existing `action_cmd` dispatcher, and every settings action reuses the modal/screen it already uses today. The only genuinely new code is the merged catalog, the filter, and the dismiss-payload dispatch in `MainScreen`.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `aicli/tui/screens.py` | Modified | `_MENU`→`_PALETTE_ENTRIES`, `_menu_option` removed, `_cmd_desc` re-sourced, `MainScreen.compose`/`BINDINGS`, new `action_palette`/`_worker_setting` |
| `aicli/tui/screens.py` | Removed | `SettingsScreen`, `_cfg_option` (moves/adapts into the catalog), menu-only actions |
| `aicli/tui/modals.py` | New | `CommandPaletteModal`; `_HELP_ROWS` updated |
| `aicli/tui/widgets.py` | Unchanged | `TicketPanel` already `width: 1fr` |
| `tests/` | New | Palette filter + dispatch tests, mirroring `tests/test_board_switcher_filter.py` |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Porting `rules:*` / `test:gemini` / `logs` is real file-IO logic, not just UI — main scope-creep source | Med | Port branch-by-branch into `_worker_setting`, reusing existing modals; no behavior redesign |
| `TicketPanel` internals may assume the narrower width | Low | Visual check at apply; CSS is `1fr`-relative |
| Removing `1`–`7`/`s` breaks muscle memory | Low | Deliberate: `s` would dangle after `SettingsScreen` is deleted, and invisible bindings tied to a deleted visual index recreate the "two systems" problem |
| `/` conflicts with another key consumer on `MainScreen` | Low | No `Input` is composed on `MainScreen`; confirm in design |

## Rollback Plan

Single-PR revert. The change is confined to `screens.py` + `modals.py` with no persistence, schema, service, or dependency change; `git revert` restores the sidebar and `SettingsScreen` exactly.

## Dependencies

None. No new packages; Textual 8.2.8 only.

## Success Criteria

- [ ] `MainScreen` shows the ticket board at full width with no sidebar.
- [ ] `/` opens the palette; typing filters commands and settings in one flat list.
- [ ] All 7 commands (`file`, `archive`, `task`, `sync`, `resume`, `claude`, `status`) launch through the existing `action_cmd`/`_worker_cmd` path unchanged (`status` already early-returns to `StatusScreen` directly, bypassing `CommandScreen`/`CommandOutputScreen` — that behavior is preserved, not "all through CommandScreen").
- [ ] All former `SettingsScreen` actions (5 credentials, gemini test, rule add/delete, logs) are reachable from the palette.
- [ ] `SettingsScreen` and `_MENU` no longer exist in the codebase.
- [ ] No test fails that was not already failing before the change.

## Proposal question round

These were decided rather than left open, per the framing "mejor UI/UX, sin agregar cosas que no sumen". Confirm or correct before spec/design:

1. Palette key is `/` (single keystroke, search-first). Prefer `ctrl+p` or `:`?
2. `1`–`7` and `s` are removed, not kept as silent power-user shortcuts.
3. Inline editing is dropped in favor of the existing `InputModal`.
4. "Recientes" is dropped, not deferred with a placeholder.
5. Rule deletion becomes one palette entry + `SelectModal` instead of one row per rule file.
