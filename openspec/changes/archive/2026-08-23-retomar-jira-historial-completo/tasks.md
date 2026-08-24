# Tasks: Resume a reopened ticket with full Jira history

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~755 (tickets.py ~270, jira.py ~45, screens.py ~55, task.py ~60, caller.py ~15, decisions.md ~30, test_tickets.py ~200 new, test_jira_comments.py ~80 new) |
| Session review budget | 800 (user override for this change) — estimate ≈ 94% of budget |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | Unit 1 (storage+jira) → Unit 2 (wiring+docs), or single PR with `size:exception` |
| Delivery strategy | single-pr |
| Chain strategy | size-exception |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: size-exception
400-line budget risk: High

`tickets.py` is a near-full rewrite; estimates like this typically run higher once written. Recommend explicit `size:exception` before `sdd-apply`, or take the two-unit split below instead.

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|---|---|---|---|---|---|
| 1 | Storage layer: per-ticket store, migration, merge-write, cap, cache, `fetch_comments`/`filter_new_comments` | PR 1 | `python -m unittest tests/test_tickets.py tests/test_jira_comments.py -v` | N/A — pure unit tests, sandboxed via `MYCONTEXT_HOME` | Revert `tickets.py`/`jira.py`/new tests; `tickets.json` untouched, nothing else depends on it yet |
| 2 | Resume wiring, attachment cache, context render, docs | PR 2 | `python tests/test_commands.py` | `ctx retomar <TICKET>` against a real reopened Jira ticket | Revert `screens.py`/`task.py`/`caller.py`/`decisions.md`; storage layer (Unit 1) stays inert/compatible |

## Phase 1: RED — `tests/test_tickets.py` (written before touching `tickets.py`)

- [x] 1.1 Create `tests/test_tickets.py`: unittest, `MYCONTEXT_HOME` env → `tempfile.TemporaryDirectory` fixture, reload `tickets` module per test.
- [x] 1.2 RED: per-ticket file created on save; two different tickets never collide.
- [x] 1.3 RED: legacy migration is additive, idempotent, fully readable; `tickets.json` bytes unchanged.
- [x] 1.4 RED: merge-on-write — sequential round+branch writes on same ticket both survive.
- [x] 1.5 RED: `format_history` caps at 5 rounds, singular/plural omitted-rounds marker, no marker when ≤5.
- [x] 1.6 RED: `get_jira_cache` watermark + processed-attachment id persist across reload.
- [x] 1.7 RED: `save_active_ticket` keeps the stored `motivo_reapertura` on empty input, same ticket only.
- [x] 1.8 RED: `save_ticket_branch` on a new ticket sets `descripcion`+`ultima_actividad` (no `KeyError`).
- [x] 1.9 RED: `other_sessions_with_ticket` excludes own PID, matches other PID, ignores stale (>24h)/malformed files.
- [x] 1.10 Run `python -m unittest tests/test_tickets.py -v`; confirm every new test fails (RED) before touching `tickets.py`.

## Phase 2: GREEN — `aicli/services/tickets.py`

- [x] 2.1 Add `_base_dir()` (env `MYCONTEXT_HOME`, never cached), `_safe_id`, `_ticket_path`, `_new_ticket`.
- [x] 2.2 Add `_read_ticket`/`_write_ticket` (atomic tmp+`os.replace`), `_mutate_ticket`, `migrate_legacy_tickets`.
- [x] 2.3 Rewrite `load_tickets()`: migrate, glob `tickets/*.json`, skip expired, never delete/rewrite.
- [x] 2.4 Rewrite `save_round`/`save_ticket_branch` via `_mutate_ticket`+`_new_ticket` (fixes missing-field bug).
- [x] 2.5 Rewrite `format_history`: `_MAX_HISTORY_ROUNDS = 5`, omitted marker, absolute round numbering.
- [x] 2.6 Add `get_jira_cache`, `save_comment_watermark`, `save_processed_attachments` (merge, never replace).
- [x] 2.7 Add `other_sessions_with_ticket` (PID/mtime/malformed-tolerant scan of `ticket_activo_*.json`).
- [x] 2.8 Fix `save_active_ticket`: empty motivo preserves the stored value for the same `ticket_id`.
- [x] 2.9 Run `python -m unittest tests/test_tickets.py -v`; confirm all GREEN.

## Phase 3: RED→GREEN — `aicli/services/jira.py` comments

- [x] 3.1 RED: create `tests/test_jira_comments.py`, mock `httpx.get`, assert 3 ordered comments and `[]` on non-200/exception.
- [x] 3.2 RED: `filter_new_comments` — watermark present/absent/`None`/empty-list.
- [x] 3.3 Run tests, confirm RED; add `_MAX_COMMENTS = 20`, `fetch_comments()` (`orderBy=-created`, `_adf_to_text`), `filter_new_comments()`.
- [x] 3.4 Run `python -m unittest tests/test_jira_comments.py -v`; confirm GREEN.

## Phase 4: Resume wiring — `aicli/tui/screens.py`

- [x] 4.1 Add `_resume_jira_context(ticket_id)`: `fetch_issue`+`fetch_comments`+`get_jira_cache`+`filter_new_comments` → delta `jira_data`.
- [x] 4.2 `_run_resume()` (L243-294): warn via `other_sessions_with_ticket`, call the helper, prefill "Motivo de reapertura" with the full text of the newest new comment (editable/deletable, not read-only), pass `ticket_id`/`jira_data` into `_execute_task`, `save_comment_watermark` after it returns.
- [x] 4.3 `_run_resume_tui()` (L385-480): identical wiring via `tui_console.request_input(..., default=...)`.

## Phase 5: Attachment cache — `aicli/commands/task.py`

- [x] 5.1 In `_execute_task` (L166-224): split attachments via `get_jira_cache()["processed_attachments"]`, hydrate cached ones, download/analyze only pending.
- [x] 5.2 Call `save_processed_attachments()` before `launch_claude`; skip caching when `GEMINI_API_KEY` is missing.

## Phase 6: Context render — `aicli/services/caller.py`

- [x] 6.1 In `launch_claude()` (L144-181): render `jira_data["comments"]` as a "## Comentarios nuevos" block inside `jira_sec`.

## Phase 7: Docs & full verification

- [x] 7.1 Add DEC entries to `knowledge/decisions.md`: per-ticket store, merge-on-write, 5-round cap, watermark-only limitation, no-TTL cache, both bug fixes, motivo prefill.
- [x] 7.2 Run `python tests/test_commands.py` and `python -m unittest discover -s tests -v`; confirm full suite GREEN, no regressions.
