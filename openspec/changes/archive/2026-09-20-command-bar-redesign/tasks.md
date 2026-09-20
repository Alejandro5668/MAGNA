# Tasks: Command Bar Redesign

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~700–750 (adds ~385 / dels ~360) |
| 400-line budget risk | High |
| Chained PRs recommended | No — `delivery_strategy` is fixed to `single-pr` for this change |
| Suggested split | Single PR, gated by `size:exception` (see Work Units for internal checkpoints) |
| Delivery strategy | single-pr |
| Chain strategy | size-exception |

Decision needed before apply: Yes
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: High

Basis (counted against actual current files, not the design's number): `screens.py` deletes `SettingsScreen` (~182 lines incl. `_worker_action`/`_rebuild_*`), `_MENU`/`_menu_option`/`_DESC_MAX`/`_cfg_option` (~45), dead `MainScreen` actions/CSS/bindings (~117) = ~344 del / adds `_PALETTE_ENTRIES`+`_setting_branch`+`_worker_setting`+`action_palette`+wiring ≈ 134. `modals.py` adds `PaletteEntry`+`filter_entries`+`CommandPaletteModal`+`_HELP_ROWS` rewrite ≈ 151 / dels ~17. New test file ≈ 100. Since design's own forecast (~655) was already over budget and my count is higher, `size:exception` is required before `sdd-apply` — do not auto-split.

### Suggested Work Units (informational — single PR, not chained)

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Palette primitives + catalog + dispatch wiring, additive alongside old sidebar | Single PR (checkpoint) | `pytest tests/test_command_palette.py -v` | `/` opens palette in running TUI | Revert `modals.py`/`screens.py` additions only |
| 2 | Delete `#left`, `SettingsScreen`, dead bindings/CSS, rewrite `_HELP_ROWS` | Single PR (checkpoint) | `pytest tests/test_commands.py -v` (same 4 pre-existing failures) | Launch TUI, confirm full-width board, no dangling refs | `git revert` restores sidebar + `SettingsScreen` |

## Phase 1: Palette Primitives (`aicli/tui/modals.py`)

- [x] 1.1 Add `PaletteEntry(NamedTuple)`: `kind, id, category, name, desc, env_key=None`.
- [x] 1.2 Add `filter_entries(entries, query)`: substring, case-insensitive over `f"{name} {desc}"`; empty/None/whitespace → all, order intact.
- [x] 1.3 Add `CommandPaletteModal(ModalScreen[tuple[str,str]|None])` cloned from `BoardSwitcherModal`: `Input`+`OptionList`, `_labels()` renders category+name+desc+`os.getenv(env_key)` badge, `on_input_changed`→`filter_entries`, `on_key` up/down/enter, empty result → one inert "Sin resultados" `Option`, dismiss `(kind,id)`/`None`.
- [x] 1.4 Add `import os`.
- [x] 1.5 Rewrite `_HELP_ROWS`: drop `1–7`/`h`/`l`/`t`/stale `j`,`k` rows; add `/` → "Abrir paleta de comandos".

## Phase 2: Catalog & Dispatch Logic (`aicli/tui/screens.py`)

- [x] 2.1 Replace `_MENU` with `_PALETTE_ENTRIES: tuple[PaletteEntry, ...]` — 7 cmd (`file,archive,task,sync,resume,claude,status`) + 5 cred (`ANTHROPIC_API_KEY,JIRA_URL,JIRA_EMAIL,JIRA_TOKEN,GEMINI_API_KEY`, `env_key` set) + `rules:add`, `rules:del`, `test:gemini`, `logs` = 16 entries.
- [x] 2.2 Re-source `_cmd_desc(command)` from `_PALETTE_ENTRIES` (`kind=="cmd"` lookup); delete `_menu_option`, `_DESC_MAX`, `_cfg_option`.
- [x] 2.3 Add `_setting_branch(opt_id) -> str`: maps id prefix to `"cred"|"rules-add"|"rules-del"|"test-gemini"|"logs"|""`.

## Phase 3: MainScreen Wiring

- [x] 3.1 `MainScreen.BINDINGS`: add `Binding("slash", "palette", "Comandos")`; remove `1`–`7`, `s`, `h`, `l`, `t`.
- [x] 3.2 Add `action_palette`/`_worker_palette` (`@work async`): `push_screen_wait(CommandPaletteModal(_PALETTE_ENTRIES))`; `("cmd",id)`→`action_cmd(id)`, `("setting",id)`→`_worker_setting(id)`.
- [x] 3.3 Add `MainScreen._worker_setting(id)`: verbatim port of `SettingsScreen._worker_action` branches via `_setting_branch`, reusing `_save_env_var`/`InputModal`/`ConfirmModal`/`SelectModal`/`LogScreen`; `rules-del` → `SelectModal(sorted(glob("*.md")))`→`ConfirmModal`→`unlink`; empty rules dir → `notify(severity="warning")`.
- [x] 3.4 `compose`: drop `Vertical(id="left")`/Collapsible loop; `TicketPanel` sole child of `#body`.
- [x] 3.5 `on_mount`: explicitly focus `TicketPanel`.
- [x] 3.6 Trim `action_jump_top`/`action_jump_bottom` to the `TicketPanel` branch only.
- [x] 3.7 Imports: drop `OptionList, Option, Collapsible, ListView, ListItem`; add `SelectModal, CommandPaletteModal, PaletteEntry`.

## Phase 4: Deletion

- [x] 4.1 Delete `SettingsScreen` (incl. `_rule_options`, `_rebuild_creds`, `_rebuild_rules`, `on_option_list_option_selected`, `_worker_action`, `DEFAULT_CSS`).
- [x] 4.2 Delete `MainScreen.on_option_list_option_selected`, `action_focus_tickets`, `action_collapse_section`, `action_expand_section`, `_set_focused_collapsible`, and the `settings` branch of `_worker_cmd`.
- [x] 4.3 Strip `MainScreen.DEFAULT_CSS`: remove `#left`, `#left:focus-within`, `Collapsible`/`CollapsibleTitle`/`Contents`, `OptionList` rules.

## Phase 5: Testing

- [x] 5.1 Create `tests/test_command_palette.py` (pattern: `tests/test_board_switcher_filter.py`): `filter_entries` empty/None/whitespace/case-insensitive/name+desc-hit/no-match.
- [x] 5.2 Catalog invariant tests: 16 entries, unique ids, every `CREDENCIAL.env_key` in `_ENV_LABELS`, every `kind=="cmd"` id in the `_worker_cmd` command set.
- [x] 5.3 Dispatch tests: every `kind=="setting"` id → non-empty `_setting_branch`; unknown id → `""`.
- [x] 5.4 `_cmd_desc` tests: resolves all 7 command ids; unknown → `""`.

## Phase 6: Verification

- [x] 6.1 `pytest tests/test_command_palette.py tests/test_board_switcher_filter.py -v` — all green (23 passed).
- [x] 6.2 `pytest tests/test_commands.py -v` — pytest collection INTERNALERRORs on this file (pre-existing: the file calls `sys.exit(1)` at module scope, unrelated to this change). Ran directly with `python tests/test_commands.py` instead (matches its own docstring/usage instructions): 19/23 passed, same 4 pre-existing failures (`tui: app.py — imports y constantes de paleta`, `tui: todas las descripciones del menú caben en una línea`, `tui: help overlay tiene todos los keybindings`, `tui: _dispatch_tui no llama asyncio.run() y usa TuiConsole`), all rooted in `aicli/tui/app.py` missing exports — a module this change never touches. No new failures.
- [x] 6.3 Grep for `SettingsScreen`, `_MENU`, `_menu_option` — zero matches outside `tests/test_commands.py` (pre-existing, explicitly out of scope per proposal) and `openspec/changes/command-bar-redesign/**` planning artifacts.
- [x] 6.4 Manual pass substitute (no interactive terminal in this environment): structural + smoke verification — `MainScreen.BINDINGS` keys confirmed (`slash, g, G, b, p, q, ?`, no `1-7/s/h/l/t`); `CommandPaletteModal(_PALETTE_ENTRIES)._labels(...)` instantiated directly and produced 16 `Option` rows for the full catalog and exactly 1 "Sin resultados" row for an empty filter; `TicketPanel.on_key` confirmed to not consume `/`; `compose()`/imports confirmed to construct with `TicketPanel` as sole `#body` child.
