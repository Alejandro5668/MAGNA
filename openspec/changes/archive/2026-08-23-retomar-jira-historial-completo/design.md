# Design: Resume a reopened ticket with full Jira history

## Technical Approach

Four independent slices over existing modules, no new packages, no classes: (1) `jira.fetch_comments` + a pure delta filter; (2) `tickets.py` moves from one shared JSON to `~/.mycontext/tickets/<id>.json` with lazy additive migration and read-merge-write mutators; (3) both resume paths in `screens.py` fetch issue+comments and forward `ticket_id`/`jira_data`; (4) `task.py` consults a per-ticket attachment cache before paying AI cost. All state stays `dict` + JSON, matching current `tickets.py`.

## Architecture Decisions

| Decision | Choice | Rejected | Rationale |
|---|---|---|---|
| Storage unit | One file per ticket, key = sanitized ticket id | Keep shared `tickets.json`; SQLite table | Removes cross-ticket loss structurally (DEC-058 continuation); SQLite would be a premature abstraction for <100 small records |
| Concurrency | `_mutate_ticket` re-reads inside the write, no locks | flock/msvcrt lock, retry loop | Confirmed product decision; lock adds Win/POSIX + stale-lock recovery for a sub-ms window |
| Expiry (>7 days) | Filter on read, never delete files | Current behavior (rewrite survivors) | The rewrite *is* the loss vector; skipping is non-destructive and rollback-safe |
| Test seam | `MYCONTEXT_HOME` env override read per call | `base_dir` param on every public fn; mocking `Path.home` | No signature churn across 5 call sites, stdlib-only. Gotcha: must not cache the base at import time |
| Test runner | stdlib `unittest` in `tests/` | pytest | Honors "no new dependencies"; `python -m unittest` works today |
| Comment delta | Fetch newest 20 (`orderBy=-created`), filter by watermark index | Full pagination; server-side JQL | Watermark-only is the confirmed decision; index lookup avoids assuming ids are numerically ordered |
| Watermark advance | After `_execute_task` returns | Before launch | Re-showing a comment is harmless; skipping it is the bug this change fixes |

## Data Flow

    resume (screens.py)
      ├─ other_sessions_with_ticket() ─→ warn (non-blocking)
      ├─ load_tickets() ─→ format_history()  [capped 5]
      ├─ jira.fetch_issue() ──────────────┐
      ├─ jira.fetch_comments() ─→ filter_new_comments(watermark)
      │                                   ↓
      └─ _execute_task(ticket_id, jira_data{+comments})
            ├─ get_jira_cache() → split attachments: cached | pending
            ├─ download+analyze(pending) → save_processed_attachments()
            └─ launch_claude() → session_context.md
      └─ save_comment_watermark()   (after return)

## File Changes

| File | Action | Description |
|---|---|---|
| `aicli/services/jira.py` | Modify | `fetch_comments`, `filter_new_comments`, `_MAX_COMMENTS = 20` |
| `aicli/services/tickets.py` | Modify | Per-ticket paths, migration, `_mutate_ticket`, cache accessors, cap, PID cross-check |
| `aicli/services/caller.py` | Modify | Render `jira_data["comments"]` block (**not in proposal table** — without it comments never reach the context file) |
| `aicli/tui/screens.py` | Modify | `_resume_jira_context()` helper used by `_run_resume` and `_run_resume_tui` |
| `aicli/commands/task.py` | Modify | Attachment cache lookup/store around the download block (L166-224) |
| `aicli/commands/sync.py` | None | Verified: `save_round`/`load_tickets`/`format_history` signatures unchanged; `current_tickets[tid]["descripcion"]` stays valid (see `_new_ticket`) |
| `tests/test_tickets.py`, `tests/test_jira_comments.py` | Create | See Testing Strategy |
| `knowledge/decisions.md` | Modify | New DEC entries |

## Interfaces / Contracts

Ticket file `~/.mycontext/tickets/<TICKET-ID>.json` (legacy keys preserved, DEC-045):

```json
{"descripcion": "...", "rondas": [], "branch": null, "ultima_actividad": 0.0,
 "jira_cache": {"last_comment_id": null,
                "processed_attachments": {"<att_id>": {"type": "image|excel|video",
                                                       "name": "qa.png", "text": "..."}}}}
```

```python
# tickets.py — private
def _base_dir() -> Path            # MYCONTEXT_HOME env or ~/.mycontext ; never cached
def _safe_id(ticket_id: str) -> str          # upper(); re.sub(r"[^A-Z0-9_-]", "_") — filename hardening
def _ticket_path(ticket_id: str) -> Path     # _base_dir()/"tickets"/f"{_safe_id(id)}.json"
def _new_ticket(ticket_id: str) -> dict      # always sets descripcion=id, rondas, branch, jira_cache
def _read_ticket(ticket_id: str) -> dict | None   # per-ticket file, else legacy entry (migrating it)
def _write_ticket(ticket_id: str, data: dict) -> None  # tmp "<id>.json.<pid>.tmp" + os.replace
def _mutate_ticket(ticket_id: str, mutate: Callable[[dict], None]) -> dict
    # read → mutate → ultima_actividad=now → atomic write. Callers MUST NOT pass a stale dict.
def migrate_legacy_tickets() -> int   # idempotent, per-ticket, writes only missing files; never touches tickets.json

# tickets.py — public (new / changed)
def load_tickets() -> dict                     # migrate, then glob tickets/*.json, skip expired (no delete)
def format_history(ticket_id: str, tickets: dict) -> str | None   # last _MAX_HISTORY_ROUNDS = 5
def get_jira_cache(ticket_id: str) -> dict
def save_comment_watermark(ticket_id: str, last_comment_id: str) -> None
def save_processed_attachments(ticket_id: str, entries: dict[str, dict]) -> None   # merge, never replace
def other_sessions_with_ticket(ticket_id: str) -> list[int]   # other PIDs' ticket_activo_*.json, mtime < 24h
def save_active_ticket(ticket_id: str, motivo_reapertura: str) -> None
    # CHANGED: empty motivo keeps the stored one for the same ticket. Prevents _execute_task(L125)
    # from wiping the reason resume just saved, now that resume passes ticket_id.

# jira.py
def fetch_comments(ticket_id: str) -> list[dict]
    # GET /rest/api/3/issue/{id}/comment?orderBy=-created&maxResults=20 → chronological
    # [{"id","author","created","body"}], body via _adf_to_text().strip(); [] + logging.warning on error
def filter_new_comments(comments: list[dict], last_comment_id: str | None) -> list[dict]
    # pure: index-of-watermark → tail; watermark absent/None → all
```

`format_history` cap output: absolute round numbering preserved, marker line `(N rondas anteriores omitidas)` (singular: `(1 ronda anterior omitida)`) emitted before the first shown round.

`task.py` order: build `processed = get_jira_cache(ticket_id)["processed_attachments"]` → hydrate `jira_images/jira_excel/jira_videos` from cache → `pending = [a for a in attachments if str(a["id"]) not in processed]` (dedupe by filename) → existing download/analyze over `pending` only, mapping local path back via `{filename: id}` → `save_processed_attachments()` **before** `launch_claude`. Only successful analyses are cached; a missing `GEMINI_API_KEY` caches nothing.

## Testing Strategy

| Layer | What | Approach |
|---|---|---|
| Unit | migration additive | seed legacy `tickets.json`, `load_tickets()`, assert both tickets present, per-ticket files created, legacy bytes unchanged |
| Unit | history cap | 8 rounds → 5 rendered, `(3 rondas anteriores omitidas)`, first shown labelled `Ronda 4` |
| Unit | merge-on-write | `save_round` then `save_ticket_branch` from a stale snapshot → both survive |
| Unit | attachment cache | merge semantics, defaults for unknown ticket, unknown-id passthrough |
| Unit | `filter_new_comments` | watermark present / absent / `None` / empty list |
| Unit | PID cross-check | own PID excluded, other PID matched, stale (>24h) and malformed files ignored |
| Integration | `fetch_comments` | `unittest.mock.patch("httpx.get")` with ADF fixture; non-200 and exception → `[]` |

All tests set `MYCONTEXT_HOME` to a `tempfile.TemporaryDirectory`; no network, no home writes.

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary is introduced. Git checkout in `_run_resume_tui` is untouched. The one filesystem concern (ticket id becomes a filename) is handled by `_safe_id` whitelisting and is covered by a unit test.

## Migration / Rollout

Lazy and additive on first `load_tickets()`. `tickets.json` is only read. Reverting the commit restores the old reader; per-ticket files become inert. Rounds recorded after migration would need manual re-merge (accepted, per proposal rollback plan).

## Open Questions

- [ ] `caller.py` is an added file vs. the proposal's Affected Areas table (~10 lines to render `jira_data["comments"]`) — confirm during tasks.
- [ ] Prefill the "Motivo de reapertura" input with the first 120 chars of the newest unseen comment (proposed; empty-reason abort stays unchanged).
