# Design: Command Bar Redesign

## Technical Approach

`CommandPaletteModal` is `BoardSwitcherModal` with its data source swapped: same `Container` box + `Input` + `OptionList`, same `on_input_changed` rebuild, same manual `up`/`down`/`enter` routing in `on_key`. The catalog (`_PALETTE_ENTRIES`) lives in `screens.py` and is *passed into* the modal, exactly as `MainScreen._worker_board` passes `panel.board_options()` — so `modals.py` never imports `screens.py`. Filtering and settings-branch selection are module-level pure functions (repo convention: testable without mounting Textual). Execution reuses `action_cmd` verbatim; settings reuse `InputModal`/`ConfirmModal`/`SelectModal`/`LogScreen`/`_save_env_var` verbatim.

## Architecture Decisions

| Decision | Choice | Rejected | Rationale |
|---|---|---|---|
| Entry shape | `PaletteEntry(NamedTuple)` in `modals.py` | dataclass; plain tuple; dict | No dataclass precedent in `aicli/tui/`. NamedTuple keeps tuple equality so filter tests assert against literals like `test_board_switcher_filter.py`. |
| Catalog location | `_PALETTE_ENTRIES` in `screens.py`, passed to the modal ctor | catalog inside `modals.py`; new `catalog.py` | `screens.py → modals.py` is the existing import direction; `_cmd_desc` needs the catalog locally. A new module for ~30 lines violates "no premature abstraction". |
| Credential badge | `env_key` field on the entry; `os.getenv` read inside the modal's `_labels()` at render time | badge baked into the catalog literal; pre-computed rows | The palette is rebuilt from live env on every open, so `_rebuild_creds`/`_rebuild_rules` disappear entirely instead of being ported. |
| Dismiss payload | `ModalScreen[tuple[str, str] \| None]`, `(entry.kind, entry.id)`, recovered by indexing `self._filtered` | encode `f"{kind}:{id}"` into `Option.id` | Setting ids already contain `:` (`k:GEMINI_API_KEY`). Index lookup avoids string surgery; `OptionSelected.option_index` covers the mouse path. |
| Empty result | One inert `"Sin resultados"` `Option`; `enter`/`selected` return early when `self._filtered` is empty | hide the list; disable `Input` | Matches the proposal, and Esc still cancels. |
| Rule deletion | One static `rules:del` entry → `SelectModal(sorted(glob("*.md")))` → `ConfirmModal` | one catalog row per rule file | Keeps the catalog static and small; filename provenance stays glob-derived, never free text. |
| `/` binding | `Binding("slash", "palette", "Comandos")` | `Binding("/", ...)` | Textual matches `Key.key`, which is `"slash"` for `/`. `TicketPanel.on_key` ignores `/` (only `r`/arrows/`enter`), so there is no consumer conflict. |
| Settings dispatch | Pure `_setting_branch(opt_id) -> str` consumed by `_worker_setting` | `if/elif` on raw prefixes inline | Makes the whole cmd-vs-setting dispatch table unit-testable with zero Textual, mirroring `move_focus`/`filter_boards`. |

### Resolved ambiguity (found in code, not in the proposal)

- **"8 commands" is a miscount.** `_MENU`'s 8th entry is `settings`, whose only behavior is pushing the deleted `SettingsScreen`. The catalog carries **7** commands + 5 credentials + 4 system/rules = **16 entries**; `settings` is dropped. Success criterion #3 should read "through the existing `action_cmd` path" — `status` already early-returns `StatusScreen`, never `CommandScreen`.
- **`_HELP_ROWS` is already stale**: `j / ↓` and `k / ↑` are advertised but no binding or `TicketPanel.on_key` branch handles them. Corrected while rewriting.
- **Command names/descriptions kept verbatim** (`file` / "Document folder", …). Renaming commands for discoverability is user-facing UX outside the proposal's scope; keeping them preserves `CommandScreen`/`CommandOutputScreen` subtitles. `_DESC_MAX` dies with the 54-column constraint.

## Data Flow

    / ─→ MainScreen.action_palette ─→ _worker_palette (@work async)
            push_screen_wait(CommandPaletteModal(_PALETTE_ENTRIES))
            keystroke ─→ on_input_changed ─→ filter_entries() ─→ OptionList rebuild
                                                 │ _labels(): os.getenv(env_key) → ✓/✗
            enter ─→ dismiss((kind, id)) | Esc ─→ dismiss(None)
                       │
            ("cmd", id) ────→ self.action_cmd(id) ──→ _worker_cmd  (UNCHANGED)
            ("setting", id) ─→ self._worker_setting(id)
                                 _setting_branch(id)
                                   cred       → InputModal → _save_env_var
                                   rules-add  → InputModal → copy .md
                                   rules-del  → SelectModal → ConfirmModal → unlink
                                   test-gemini→ gemini.test_connection
                                   logs       → push_screen(LogScreen)

## File Changes

| File | Action | Description |
|---|---|---|
| `aicli/tui/modals.py` | Modify | New `PaletteEntry`, `filter_entries()`, `CommandPaletteModal` (next to `filter_boards`/`BoardSwitcherModal`); `import os`; `_HELP_ROWS` rewritten. |
| `aicli/tui/screens.py` | Modify | `_MENU`→`_PALETTE_ENTRIES`; `_cmd_desc` re-sourced; new `_setting_branch`, `action_palette`, `_worker_palette`, `_worker_setting`; `compose`/`on_mount`/`BINDINGS`/`DEFAULT_CSS`; `action_jump_top`/`jump_bottom` keep only the `TicketPanel` branch; import `SelectModal, CommandPaletteModal, PaletteEntry`. |
| `aicli/tui/screens.py` | Delete | `SettingsScreen` (incl. `_rule_options`, `_rebuild_creds`, `_rebuild_rules`, `_worker_action`), `_MENU`, `_menu_option`, `_DESC_MAX`, `_cfg_option`, `MainScreen.on_option_list_option_selected`, `action_focus_tickets`, `action_collapse_section`, `action_expand_section`, `_set_focused_collapsible`, the `settings` branch of `_worker_cmd`. Now-unused imports: `OptionList`, `Option`, `Collapsible`, `ListView`, `ListItem`, `Vertical`. |
| `aicli/tui/screens.py` | Keep | `_ENV_LABELS` (still the label source for the credential branch and catalog names), `_save_env_var`, `LogScreen`. |
| `aicli/tui/widgets.py` | Unchanged | `TicketPanel` is `width: 1fr`, `#left`-independent (verified widgets.py:223-224). |
| `tests/test_command_palette.py` | Create | Filter + catalog + dispatch unit tests. |

CSS removed from `MainScreen.DEFAULT_CSS`: `#left`, `#left:focus-within`, all `Collapsible`/`CollapsibleTitle`/`Contents`, all `OptionList` rules. `#body` keeps `height: 1fr; border-top; margin-top` and gains `TicketPanel` as its sole child.

## Interfaces / Contracts

```python
# modals.py
class PaletteEntry(NamedTuple):
    kind: str            # "cmd" | "setting"
    id: str              # "task" | "k:GEMINI_API_KEY" | "rules:add" | "rules:del" | "test:gemini" | "logs"
    category: str        # "COMANDO" | "CREDENCIAL" | "REGLAS" | "SISTEMA"
    name: str
    desc: str
    env_key: str | None = None      # only CREDENCIAL: drives the live ✓/✗ badge

def filter_entries(entries: Sequence[PaletteEntry], query: str | None) -> list[PaletteEntry]:
    """Substring, case-insensitive, over f'{name} {desc}'. Empty/None/blank → all, order intact."""

class CommandPaletteModal(ModalScreen[tuple[str, str] | None]):
    """BoardSwitcherModal's box/Input/OptionList/on_key verbatim; _labels() renders
    category tag + name + desc (+ badge when env_key). dismiss((kind, id)) | dismiss(None)."""
    def __init__(self, entries: Sequence[PaletteEntry]) -> None: ...

# screens.py
_PALETTE_ENTRIES: tuple[PaletteEntry, ...]   # 7 cmd + 5 cred + rules:add + rules:del + test:gemini + logs
def _cmd_desc(command: str) -> str           # kind == "cmd" lookup, "" when unknown
def _setting_branch(opt_id: str) -> str      # "cred"|"rules-add"|"rules-del"|"test-gemini"|"logs"|""
```

`MainScreen`: `BINDINGS = [slash→palette "Comandos", g, G (show=False), b (show=False), p "Project", q "Quit", ? "Help"]`. `on_mount` focuses `TicketPanel` explicitly rather than relying on first-focusable ordering. `_worker_setting` is a verbatim port of `SettingsScreen._worker_action` minus the two `_rebuild_*` calls, with the `rules:del:{name}` prefix branch replaced by the `SelectModal` flow (empty rules dir → `notify(severity="warning")` and return).

## Testing Strategy

Convention: `unittest`, pure functions, no Textual mount (`tests/test_board_switcher_filter.py`).

| Layer | What | Approach |
|---|---|---|
| Unit | `filter_entries`: empty / `None` / whitespace → all; case-insensitive hit on `name`; hit on `desc` ("gemini" → `GEMINI_API_KEY`); no match → `[]` | direct calls, `tests/test_command_palette.py` |
| Unit | Catalog invariants: 16 entries, unique ids, non-empty name/desc, every `CREDENCIAL.env_key` in `_ENV_LABELS`, every `kind=="cmd"` id in the `_worker_cmd` set | direct calls |
| Unit | Dispatch: every `kind=="setting"` id maps to a non-empty `_setting_branch`; unknown id → `""`; `("cmd", …)` vs `("setting", …)` payload projection | table-driven |
| Unit | `_cmd_desc` resolves all 7 command ids; unknown → `""` | direct calls |
| Manual | `/` opens palette, filter+Enter launches, board renders full width, all former settings reachable | one scripted pass at apply |

**Existing tests (grepped, not assumed):** no test imports `SettingsScreen`. `tests/test_commands.py` references `_MENU`/`_menu_option`/`_DESC_MAX` in three tests (`test_tui_imports`, `test_tui_menu_no_wrap`, `test_tui_help_rows`) — all three already fail with `ImportError` because they import from `aicli.tui.app`, which has exported only `MainScreen`/`ProjectScreen` since an earlier split. **Left untouched**: excluded by the proposal, already red, and partial edits to a module that cannot import add no verification value. `tests/test_board_switcher_filter.py` is unaffected.

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary is added. The file I/O in `_worker_setting` (`~/.mycontext/.env` write, `.md` copy, `unlink`) is a verbatim port of shipped `SettingsScreen` logic. Behavior-preservation requirement for apply: the `rules:del` filename must stay glob-derived via `SelectModal`, never free text, so no path component reaches `unlink()` from user input.

## Migration / Rollout

No migration. No schema, dependency, service, or persisted state change. Rollback = `git revert` of the single commit.

**Line forecast:** `screens.py` ≈ 110 add / 300 del, `modals.py` ≈ 135 add / 20 del, tests ≈ 90 add → **≈ 655 changed lines**, deletion-heavy. Above the 400-line budget. Recommendation for `sdd-tasks`: two chained slices — (1) `PaletteEntry` + `filter_entries` + `CommandPaletteModal` + `_PALETTE_ENTRIES` + `_worker_setting` + `/` binding + tests (additive; palette works alongside the surviving sidebar), (2) remove `#left`, `SettingsScreen`, dead bindings/CSS/imports and rewrite `_HELP_ROWS`. Each slice is independently shippable, verifiable, and revertible. Fallback: single PR with `size:exception`, precedent `2026-09-19-dashboard-story-switcher` (~640 lines).

## Open Questions

- None blocking.
