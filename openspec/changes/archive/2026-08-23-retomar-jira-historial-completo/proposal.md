# Proposal: Resume a reopened ticket with full Jira history

## Intent

`ctx retomar` never re-queries Jira: `_run_resume` / `_run_resume_tui` (`aicli/tui/screens.py` L243-294, L385-480) pass neither `ticket_id` nor `jira_data` to `_execute_task`. QA's reopen comment and its attachment must be pasted by hand on every reopen. Two constraints shape the fix: parallel MAGNA terminals must never mix ticket data, and `session_context.md` must stay nutritious but bounded.

## Scope

### In Scope
- `jira.fetch_comments(ticket_id)` — REST `GET /issue/{id}/comment`, ADF reused via `_adf_to_text`, no AI cost.
- Both resume call sites fetch issue + comments and pass `ticket_id` / `jira_data` into `_execute_task`.
- Storage split: `~/.mycontext/tickets/<ticket_id>.json`, one-time lazy migration from `tickets.json` (keys `descripcion`/`rondas`/`branch`/`investigado`/`hecho`/`tener_en_cuenta` preserved per DEC-045).
- Per-ticket cache: `last_comment_id` watermark + processed-attachment results keyed by attachment id, so only new comments/attachments hit the AI pipeline.
- `format_history` capped to the last 5 rounds with an explicit `(N rondas anteriores omitidas)` marker.
- Non-blocking warning when another PID's `ticket_activo_*.json` holds the same ticket.
- New DEC entries in `knowledge/decisions.md`.

### Out of Scope
- Mutual exclusion (lock files, advisory locks, retry/backoff) — see Approach.
- Size cap/warning in `builder.build_context()` — orthogonal follow-up slice.
- Any change to `session_ctx_*` (already PID-scoped, DEC-058). `save_active_ticket` itself gets one small in-scope fix (see Risks table) so it stops wiping `motivo_reapertura` once resume starts passing `ticket_id` — the PID-scoped file layout it writes to is unchanged.

## Capabilities

### New Capabilities
- `ticket-history-store`: per-ticket persistence, migration, capped history rendering.
- `jira-resume-context`: comment/attachment retrieval and delta caching on resume.

### Modified Capabilities
- None (no `openspec/specs/` exists yet).

## Approach

File-per-ticket, not a lock — the idiomatic continuation of DEC-058 (isolate by key, not by coordinating access), keyed by `ticket_id` instead of `pid`. It removes cross-ticket loss structurally: today `_save` rewrites the whole shared file through a shared `tickets.tmp`, and `load_tickets()` purges by rewriting everything it read.

**Decision on the open question (same ticket, two terminals):** true concurrency control is out of scope. Instead each mutator (`save_round`, `save_ticket_branch`, cache writes) re-reads its own ticket file and merges its delta immediately before writing, shrinking the window to the write itself; and resume warns when the ticket is already open elsewhere. Rationale: a post-hoc warning cannot prevent or repair a lost write, whereas merge-on-write makes loss require a sub-millisecond interleave, and a lock would contradict DEC-058 plus add Windows/POSIX semantics and stale-lock recovery for a residual case.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `aicli/services/jira.py` | Modified | Add `fetch_comments()` |
| `aicli/services/tickets.py` | Modified | Per-ticket paths, migration, merge-write, capped history, cache accessors |
| `aicli/tui/screens.py` | Modified | Both resume paths fetch Jira; duplicate-session warning |
| `aicli/commands/task.py` | Modified | Consult attachment cache before reprocessing |
| `aicli/commands/sync.py` | Confirmed unchanged | Design verified `save_round`/`load_tickets`/`format_history` call sites stay valid as-is |
| `aicli/services/caller.py` | Modified (found in design, not in original scope) | ~10 lines to render `jira_data["comments"]` into `session_context.md` — without this the fetched comments never reach Claude |
| `knowledge/decisions.md` | Modified | New DEC entries |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Migration loses existing history | Med | Lazy, additive, non-destructive: keep `tickets.json` as read-only fallback until every ticket migrates |
| Capped history looks like data loss | Med | Explicit omitted-rounds marker in Spanish |
| Comments + attachments inflate context | Med | Delta since `last_comment_id` only; cached attachment summaries |
| Stale `ticket_activo_*.json` triggers false warning | Low | Warning is informational, never blocks |
| No tests exist for `tickets.py` / `jira.py` | High | Spec phase defines tests for migration, cap, and cache before refactor |
| `_execute_task`'s `save_active_ticket(ticket_id, "")` wipes `motivo_reapertura` once resume starts passing `ticket_id` (found in design) | High if unfixed | Design: `save_active_ticket` preserves a stored non-empty motivo when called with an empty one |
| `save_ticket_branch` creates entries missing `descripcion`/`ultima_actividad`, causing `KeyError` in `format_history` or premature purge (found in design, pre-existing bug) | Med | Design: `_new_ticket()` always fills both fields |

## Rollback Plan

Revert the commit. `tickets.json` is never deleted or rewritten by the migration, so reverted code reads the original file; per-ticket files under `~/.mycontext/tickets/` become inert leftovers. Rounds recorded only after migration would need manual re-merge — acceptable, and the reason migration must stay additive.

## Dependencies

- Jira credentials already configured (`JIRA_URL`, `_headers()`); no new packages (stdlib + `httpx`).

## Product Decisions Confirmed (2026-08-23)

The four assumptions below were made under `auto` execution mode and were explicitly confirmed by the user before proceeding to spec/design — no changes to the Approach section were needed, all defaults were accepted as proposed:

- History cap: 5 rounds, confirmed.
- Same-ticket concurrency: warning-only (no lock), confirmed.
- Comment delta strategy: watermark-only, edited old comments are not re-read — accepted as a known limitation.
- Attachment cache: never expires — accepted, no TTL.

## Success Criteria

- [ ] Resuming a reopened ticket shows QA's latest comment and attachment without manual pasting.
- [ ] Two terminals on different tickets never lose each other's rounds or branch.
- [ ] Re-resuming the same ticket reprocesses no already-cached attachment.
- [ ] `session_context.md` history stays bounded with a visible omitted-rounds marker.
- [ ] Pre-existing `tickets.json` history is fully readable after migration.
