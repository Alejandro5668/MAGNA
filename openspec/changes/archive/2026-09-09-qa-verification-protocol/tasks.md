# Tasks: QA Verification Protocol for Bug-Shaped Tasks

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~340-400 (new `qa_protocol.py` ~154 lines dominates; wiring ~40; tickets/sync ~28; tests ~120; docs ~25) |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Suggested split | Single PR — phases below serve as internal review checkpoints |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Medium

Note: estimate sits close to the 400-line budget, driven almost entirely by the literal `QA_PROTOCOL` text block (static content, low review complexity per line) and the two test files. If `sdd-apply` finds the real diff crossing 400, re-run this forecast before proceeding.

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | `qa_protocol.py` + wiring into `builder.py`/`task.py` | PR 1 (single PR, checkpoint 1) | `python tests/test_commands.py` | N/A — pure functions, no live Claude session needed to verify | Revert `qa_protocol.py`, `builder.py`, `task.py` diffs |
| 2 | Outcome tracking (`tickets.py`/`sync.py`) + both test files | PR 1 (single PR, checkpoint 2) | `python tests/test_tickets.py` | N/A — filesystem-only via `MYCONTEXT_HOME` tempdir | Revert `tickets.py`, `sync.py`, test diffs |

## Phase 1: Foundation — `aicli/services/qa_protocol.py`

- [x] 1.1 Create `aicli/services/qa_protocol.py`; stdlib-only imports (`re`, `unicodedata`, `pathlib.Path`).
- [x] 1.2 Add `QA_PROTOCOL` constant — exact Spanish text from design.md, with sentinels `<E2E_DIR>` and `<QA_RESULT_DIR>`.
- [x] 1.3 Add `render_qa_protocol(project_id: int | None = None) -> str` per design Decision 1 (`str.replace`, `Path.home()`, not `_base_dir()`).
- [x] 1.4 Add `_REOPEN_MARKER`, `_BUG_KEYWORDS`, `_BUG_RE`, `_normalize()`, `is_bug_task()` — exact bodies from design.md (Decisions 5-7). Pure, no module-level mutable state.

## Phase 2: Wiring — `builder.py` + `task.py` (depends on Phase 1)

- [x] 2.1 `builder.py`: import `render_qa_protocol`; add `es_bug: bool = False` to `build_context` signature.
- [x] 2.2 `builder.py`: when `es_bug=True`, prepend `render_qa_protocol(modules[0].project_id if modules else None)` as `fragments[0]`, ahead of team-rule fragments (exact diff sketch).
- [x] 2.3 `task.py`: import `is_bug_task` in `_execute_task`; compute `es_bug = is_bug_task(task_desc, jira_data)` immediately before the `build_context` call.
- [x] 2.4 `task.py:288`: pass `es_bug=es_bug` to `build_context` — the only call site changed; no edits to `screens.py` or `claude_cmd.py`.

## Phase 3: Outcome Tracking — `tickets.py` + `sync.py` (independent of Phase 1-2, can run in parallel)

- [x] 3.1 `tickets.py`: add `_qa_results_dir()` returning `_base_dir() / "qa_results"` (sibling of `tickets/`, not inside it).
- [x] 3.2 `tickets.py`: add `read_qa_result(ticket_id) -> dict | None` — read via `_safe_id()`-sanitized path, parse JSON, delete-after-read on both success and corrupt-file paths, per Decisions 2-4.
- [x] 3.3 `tickets.py`: extend `save_round(...)` with `qa_verified: bool | None = None`, appended last in the `ronda` dict (after `memoria`).
- [x] 3.4 `sync.py`: add `read_qa_result` to the existing `tickets` import; inside `if save:`, immediately before `save_round` (`sync.py:390`), read the result and derive `qa_verified` via `isinstance(data.get("verified"), bool)`; pass it through.

## Phase 4: Tests (depends on Phases 1-3)

- [x] 4.1 `tests/test_commands.py`: replace the `callable(build_context)` assertion (`:214/218`) with the 8 `is_bug_task` cases + 5 `build_context(es_bug=...)` cases from design.md's Testing Strategy (`check()` harness).
- [x] 4.2 `tests/test_tickets.py`: add the 8 `read_qa_result`/`save_round(qa_verified=...)` round-trip cases from design.md's Testing Strategy (stdlib `unittest`, `MYCONTEXT_HOME`).

## Phase 5: Documentation (depends on Phase 1-4 landing)

- [x] 5.1 `knowledge/decisions.md`: append `DEC-081` documenting the QA_PROTOCOL injection + `qa_verified` ground-truth tracking, matching the existing Decisión/Por qué/Alternativas descartadas format.
