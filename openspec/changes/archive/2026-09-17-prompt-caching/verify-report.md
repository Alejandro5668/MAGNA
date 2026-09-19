# Verification Report: prompt-caching

**Change**: prompt-caching
**Mode**: Full artifact set (proposal, design, specs, tasks) — Strict TDD active
**Verdict**: PASS WITH NOTES

## Completeness

| Task | Status | Evidence |
|------|--------|----------|
| 1.1/1.2 Deterministic ordering | Done | `task.py`: `select(Module).where(Module.project_id == project.id).order_by(Module.id)`; covered by `ModuleQueryOrderingTestCase` (2 tests, pass) |
| 2.1-2.5 Cacheable system prefix / user-turn split | Done | `task.py` `_detect_relevant_modules`: `system_blocks` list with `type: text`, `cache_control: {"type": "ephemeral"}`; `user_prompt` holds `task_desc`/`file_context`/JSON instruction; covered by `PromptCachingSystemBlockTestCase` (4 tests, pass) |
| 3.1/3.2 Cache-usage observability | Done | `logging.info(...)` after `client.messages.create`, uses `usage.cache_creation_input_tokens or 0` / `usage.cache_read_input_tokens or 0` (None-safe); covered by `CacheUsageObservabilityTestCase` (2 tests, pass) |
| 4.1/4.2 Contract preservation | Done | `model="claude-sonnet-5"`, `thinking={"type": "adaptive"}` unchanged; JSON parse/name-filter unchanged; covered by `ContractPreservationTestCase` (2 tests, pass) |
| 5.1 Live cache-effectiveness check | Deferred — see below | Not executable in this environment (no `ANTHROPIC_API_KEY`) |
| 5.2 Real prefix token-size estimate | Executed — see below | Synthetic estimation performed, threshold clearance confirmed |

Spot-checked 4 of the 11 completed tasks directly against the diff (exceeds the 3-item minimum): 1.2, 2.5, 3.2, 4.1/4.2 all match the checked-off description exactly. No discrepancy found between `tasks.md` claims and actual code.

## Test Execution

Command: `.venv/Scripts/python.exe -m pytest tests/ --ignore=tests/test_commands.py -v`
Exit code: 0
Result: **29/29 passed** (19 pre-existing + 10 new from `tests/test_prompt_caching.py`), 0 failures, 0 regressions.
`tests/test_commands.py` is excluded — pre-existing standalone script (`sys.exit(1)` at import time, crashes pytest collection), unrelated to this change, already flagged in apply-progress.

## Spec Compliance Matrix

| Requirement | Scenario | Status | Evidence |
|---|---|---|---|
| Cacheable System Prefix | Repeated call shares identical prefix | PASS (unit) | `test_system_byte_identical_across_different_task_desc` |
| Cacheable System Prefix | Task description never affects cached block | PASS (unit) | `test_task_desc_absent_from_system_present_in_messages` |
| Cacheable System Prefix | Empty module list never reaches this function | PASS (design-level, pre-existing guard) | `task.py:136-138` early-return guard unchanged by this diff |
| Deterministic Module Listing Order | Identical module set → identical listing text | PASS (unit) | `test_order_by_module_id_produces_ascending_sql`, `test_execute_task_query_orders_by_module_id` |
| Output Format / Behavior Preservation | JSON parse succeeds unchanged | PASS (unit) | `test_json_parse_and_filter_by_name` |
| Cache Effectiveness Observability | Cache write/read logged | PASS (unit, None-safe) | `test_logs_cache_usage_when_present`, `test_none_cache_usage_does_not_raise` |
| Graceful Degradation Below Cache Threshold | Small project degrades to uncached behavior | PASS (design-level — unconditional `cache_control`, API-side silent ignore is Anthropic's documented behavior; not independently re-verified live) | No live test; consistent with SDK contract and unchanged error handling |

All unit-testable scenarios have a passing covering test at runtime. The two scenarios requiring a live API round-trip (cache-read observability against the real API, and the below-threshold live no-op) are not independently confirmed here — see Phase 5 findings below.

## Phase 5 Deferred Checks (this phase's primary responsibility)

### 5.1 — Live cache-effectiveness check
**Result: NOT EXECUTABLE IN THIS ENVIRONMENT.**
`ANTHROPIC_API_KEY` is not present in the verification environment. No live call was made against `_detect_relevant_modules` or an equivalent harness. This is reported as an explicit open item, not fabricated as passing.
**Required follow-up**: a human with API access must run two consecutive `ctx task` invocations (or an equivalent minimal harness exercising the same `system=`/`messages=` shape) against an unchanged module set within the cache TTL and confirm `response.usage.cache_read_input_tokens > 0` on the second call.

### 5.2 — Real prefix token size
**Result: EXECUTED.**
No SDK-local token-counting utility is available offline (`anthropic.Anthropic.messages.count_tokens` exists but is a real network endpoint requiring an API key, same constraint as 5.1; `tiktoken` is not installed and is not the correct tokenizer for Claude regardless). Used a character-count approximation (~3.5–4 chars/token, standard heuristic) against two synthetic listings built in the exact format `_detect_relevant_modules` produces (`- {name}: {description} | archivo: {path}` + optional `Contexto: {snippet[:300]}` lines + `PROYECTO.md` block):

- **Realistic listing (25 modules, with content snippets, plus a representative ~1,000-char `PROYECTO.md`)**: 12,466 chars → **~2,270–3,560 estimated tokens**, roughly 2.2x–3.5x above the ~1,024-token Sonnet minimum cacheable-prefix threshold. Comfortable margin.
- **Minimal listing (5 modules, no snippets, no `PROYECTO.md`)**: 473 chars → **~118 estimated tokens**, well below the threshold — confirms the Graceful Degradation scenario is reachable for genuinely small projects, not just a theoretical branch.

Conclusion: for any project with a non-trivial number of documented modules (roughly 10+ modules with descriptions, or fewer with doc snippets/`PROYECTO.md` present), the cached prefix clears the threshold with margin. Very small/new projects legitimately fall below it and exercise the degradation path, which is itself a required and tested scenario. This is an estimate, not an SDK-verified count — flagged as approximate, not a hard measurement.

## Scope / Diff Integrity

`git diff --stat` for tracked files touched by this change:
```
aicli/commands/task.py | 33 +++++++++++++------
```
Plus new untracked file `tests/test_prompt_caching.py` (182 lines). Confirmed: the diff touches only `task.py` and the new test file — matches `tasks.md`'s stated scope and the apply-progress diff-size claim (+24/-9 in task.py, 215 total changed lines). No new scope creep found.

Note (out of scope, pre-existing, not part of this change): the working tree also has uncommitted changes to `knowledge/decisions.md`, `knowledge/flow.md`, `knowledge/progress.md`, predating this SDD session (last commit touching `decisions.md` is 2026-09-10, unrelated to prompt-caching). These are not part of the prompt-caching diff and are not evaluated by this report.

## Issues

**CRITICAL**: None.

**WARNING**: None.

**SUGGESTION**:
- Phase 5.1 (live cache-read confirmation) remains an open manual-verification item — recommend running it once API access is available, before or shortly after archive, since it's cheap (a few cents) and closes the loop on the one scenario no automated test can cover offline.

## Final Verdict

**PASS WITH NOTES** (equivalent to PASS WITH WARNINGS in report taxonomy, downgraded to "notes" since no WARNING/CRITICAL was found — only one explicitly-scoped, pre-acknowledged open item that was never an implementation blocker per `tasks.md`).

The change is ready to archive. Task completion, spec compliance (for all offline-testable scenarios), and diff scope are all confirmed clean. The one remaining item (5.1 live cache-read confirmation) is non-blocking per the original task design and can be tracked as a follow-up rather than gating archive.
