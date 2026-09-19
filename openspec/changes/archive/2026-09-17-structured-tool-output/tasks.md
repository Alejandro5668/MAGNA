# Tasks: Structured Tool Output

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | Unit A ≈125, Unit B ≈426, Single PR ≈551 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | A → B (A merges first; B depends on A for `_extract_tool_input`) |
| Delivery strategy | exception-ok (user pre-accepted `size:exception` for Unit B) |
| Chain strategy | size-exception |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: size-exception
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| A | Migrate `_detect_relevant_modules` (task.py) to forced tool output; add shared `_extract_tool_input` in `indexer.py` | PR 1 | `.venv\Scripts\python.exe -m pytest tests/test_prompt_caching.py -v` | `ctx task "<desc>"` on a real project | Revert `task.py` diff + `_extract_tool_input` addition in `indexer.py`; no other unit depends on A yet |
| B | Extract `_messages_create_retry`/`_call_claude_tool`; migrate `generate_case_summary`, `document_zone`, `document_architecture`; delete dead JSON-repair code | PR 2 (base = A; `size:exception` pre-accepted, ≈426 lines) | `.venv\Scripts\python.exe -m pytest tests/test_structured_output.py tests/test_prompt_caching.py -v` | `ctx init`, `ctx file <zona>`, `ctx sync` on a real project | Revert `indexer.py` diff only; `_call_claude` markdown callers unaffected by design |

## Unit A — `_detect_relevant_modules` (task.py)

- [x] A1 RED — `tests/test_prompt_caching.py`: rewrite `_stub_response` to emit a `tool_use` block (`SimpleNamespace(type="tool_use", name=..., input=...)`) preceded by a non-`tool_use` block; rewrite `test_json_parse_and_filter_by_name` to assert filtering via `input["modules"]`.
- [x] A2 RED — add test: `_detect_relevant_modules` sends `tools=[MODULE_SELECTION_TOOL]` and `tool_choice={"type":"tool","name":"seleccionar_modulos"}`.
- [x] A3 RED — add test: `_extract_tool_input` skips leading `thinking`/`text` blocks; raises `RuntimeError` when no matching tool block exists (mirrors the `_extract_text` bug fixed in `ba41364`).
- [x] A4 RED — add test: `system`/`cache_control`/`thinking`/`model` kwargs unchanged (change-1 non-regression); add a code comment near `_detect_relevant_modules` documenting the cache-prefix-shift caveat — `tools` precedes `system` in the cache key, so the first post-deploy call is an expected cache *write*, not a bug.
- [x] A5 Run A1-A4 — confirm RED against current code.
- [x] A6 GREEN — add `_extract_tool_input(content_blocks, tool_name) -> dict` to `indexer.py` next to `_extract_text` (~line 47).
- [x] A7 GREEN — add `MODULE_SELECTION_TOOL` constant to `task.py`; import `_extract_tool_input` alongside the existing `_extract_text` import (task.py:14).
- [x] A8 GREEN — `task.py:62-68`: add `tools=`/`tool_choice=` to `messages.create`; rewrite the user-prompt instruction text per design's diff (task.py:52-59).
- [x] A9 GREEN — `task.py:79-81`: replace the `raw_decode` block with `_extract_tool_input(response.content, MODULE_SELECTION_TOOL["name"])["modules"]`.
- [x] A10 Run `pytest tests/test_prompt_caching.py -v` — confirm all green, zero network calls.

## Unit B — retry extraction + 3 call-site migrations (indexer.py)

- [x] B1 RED — new `tests/test_structured_output.py`: baseline test — `_call_claude` still returns `tuple[str,int]`, and kwargs sent to `messages.create` contain no `tools` key (must pass pre-refactor; guards `generate_module_content`/`analyze_file_deep`/`generate_project_md` byte-unaffected).
- [x] B2 RED — add tests for the not-yet-existing `_call_claude_tool`/`_messages_create_retry`: forced `tools`/`tool_choice` reach `messages.create`; backoff retried on `RateLimitError`.
- [x] B3 Run B1-B2 — confirm baseline (B1) passes now, B2 fails (RED).
- [x] B4 GREEN — extract `_messages_create_retry(context, estimated_tokens, **kwargs) -> Message` from `_call_claude`'s retry loop (indexer.py:192-219), preserving logging/backoff exactly.
- [x] B5 GREEN — rewrite `_call_claude` as a thin wrapper over `_messages_create_retry`; add `_call_claude_tool(prompt, tool, context, max_tokens, model) -> tuple[dict,int]` per design.
- [x] B6 Run B1-B2 — confirm both green (baseline preserved, new tool-call path works).
- [x] B7 RED — add tests: `document_zone`/`document_architecture` send the same `DOCUMENT_MODULES_TOOL` object; `input={"modules":[...]}` unwraps to bare `list[dict]`; `generate_case_summary` returns `(jira, 4-key memoria, tokens)` and a missing required key raises `KeyError` (no empty-string fallback); all 3 sites' `inspect.getsource` contains no `json.loads`/`raw_decode`.
- [x] B8 Run B7 — confirm RED (schemas/call sites not yet migrated).
- [x] B9 GREEN — add `MODULE_ITEM_SCHEMA`, `DOCUMENT_MODULES_TOOL`, `CASE_SUMMARY_TOOL` constants to `indexer.py` (verbatim `description` text carried over from the current prompts).
- [x] B10 GREEN — migrate `document_zone` (indexer.py:437) and `document_architecture` (indexer.py:706) to `_call_claude_tool(prompt, DOCUMENT_MODULES_TOOL, ...)`; delete the now-dead prose-JSON instruction blocks.
- [x] B11 GREEN — migrate `generate_case_summary` (indexer.py:248) to `_call_claude_tool(prompt, CASE_SUMMARY_TOOL, ...)`; remove `required_keys`/try-except (indexer.py:287-299); direct-index the 4 memoria keys.
- [x] B12 Run B7 — confirm green.
- [x] B13 Delete `_reparar_json` (indexer.py:132) and `_parse_json_claude` (indexer.py:166); confirm zero remaining callers via grep.
- [x] B14 Delete `import json` (indexer.py:6) only after grep confirms no other `json.` use remains in the file.
- [x] B15 Run full `pytest` suite — confirm all green, zero regressions.

## Cross-Cutting

- [ ] X1 After Unit A merges: real `ctx task` run — confirm the 1st post-deploy call is a cache write and the 2nd+ calls show `cache_read_input_tokens > 0`, matching A4's documented caveat (expected, not a defect). **Not runnable from this apply batch** — requires a real project + Jira/API key; needs to be executed by the user/orchestrator post-merge. Static verification done instead: added `Change1CachingSurvivesUnitBTestCase` (`tests/test_structured_output.py`) proving Unit B's 3 migrated call sites never touch `system`/`cache_control`, and that `_messages_create_retry`/`_call_claude_tool` forward `**kwargs` untouched — so Unit A's cache prefix reaches `messages.create` exactly as `task.py` builds it, unaffected by Unit B.
- [ ] X2 After Unit B merges: manual smoke — `ctx init`, `ctx file <zona>`, `ctx task`, `ctx sync` — confirm unchanged output shape end-to-end. **Not runnable from this apply batch** (no real project/Jira/API key in this sandbox) — remains an open item for the user/orchestrator post-merge. What WAS verified as a substitute: full `pytest` suite green (53/53) including all 3 migrated call sites' payload shape/unwrapping/error-propagation contracts, plus the pre-existing 33-test baseline (`test_caller.py`, `test_jira_comments.py`, `test_prompt_caching.py`, `test_tickets.py`) unaffected.
