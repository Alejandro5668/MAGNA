# Tasks: Prompt Caching for Module Detection (`ctx task`)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~220-260 (task.py ~55-65; tests/test_prompt_caching.py ~180-200 new) |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Deterministic order + cached prompt split + observability, one function | PR 1 (single) | `py -m unittest tests/test_prompt_caching.py -v` | N/A — offline mocked SDK only; live cache verification deferred to sdd-verify | `aicli/commands/task.py` (`_detect_relevant_modules`, task.py:134) + `tests/test_prompt_caching.py`; revert diff, no migration/config to unwind |

## Phase 1: Deterministic Module Ordering

- [x] 1.1 RED: `tests/test_prompt_caching.py` — assert the module query includes `ORDER BY` on `Module.id` (`"ORDER BY" in str(select(...).order_by(Module.id))`).
- [x] 1.2 GREEN: `aicli/commands/task.py:134` — add `.order_by(Module.id)` to the `select(Module)` query.

## Phase 2: Cacheable System Prefix / Variable User Turn Split

- [x] 2.1 RED: `tests/test_prompt_caching.py` — mock `anthropic.Anthropic`, call `_detect_relevant_modules`, assert `system` is a list, `system[0]["type"]=="text"`, `system[0]["cache_control"]=={"type":"ephemeral"}`.
- [x] 2.2 RED: same test module — assert `task_desc` sentinel is absent from `system[0]["text"]` and present in `messages[0]["content"]` (prefix-purity).
- [x] 2.3 RED: assert module-listing and `PROYECTO.md` sentinels appear only in `system[0]["text"]`.
- [x] 2.4 RED: two calls, same modules/`project_context`, different `task_desc` — assert `system[0]["text"]` is byte-identical across calls.
- [x] 2.5 GREEN: `aicli/commands/task.py` — restructure `_detect_relevant_modules`: build `system_blocks` (listing + `PROYECTO.md`, `cache_control: {"type": "ephemeral"}`) and move `task_desc`/`file_context`/JSON instruction into `messages[0]["content"]`; pass `system=system_blocks` to `client.messages.create`.

## Phase 3: Cache-Usage Observability

- [x] 3.1 RED: assert `logging.info` is called with `cache_creation_input_tokens`/`cache_read_input_tokens` values after a successful call; assert no exception when `usage.cache_creation_input_tokens`/`cache_read_input_tokens` are `None`.
- [x] 3.2 GREEN: `aicli/commands/task.py` — after `response = client.messages.create(...)`, add `logging.info(...)` line matching `_call_claude`'s format (`indexer.py:202-206`), using `usage.cache_creation_input_tokens or 0` and `usage.cache_read_input_tokens or 0`.

## Phase 4: Contract-Preservation Regression

- [x] 4.1 RED/GREEN: assert `model="claude-sonnet-5"` and `thinking={"type": "adaptive"}` are unchanged in `call_args.kwargs` after the restructuring.
- [x] 4.2 RED/GREEN: assert `json.JSONDecoder().raw_decode` still parses the stubbed response text and the returned list still filters `modules` by parsed names only.

## Phase 5: Non-Blocking Follow-Up (owned by sdd-verify)

- [ ] 5.1 Record as an explicit sdd-verify task (not an implementation blocker): empirically confirm Sonnet's ~1,024-token minimum cacheable prefix against a live `ctx task` call, since no SDK constant or fetch tool confirms it in this phase.
- [ ] 5.2 Record as an explicit sdd-verify task (not an implementation blocker): run two `ctx task` calls <5 min apart on a real large-project DB, confirm run 2 logs `cache_read_input_tokens > 0`, and record run 1's `cache_creation_input_tokens` as the measured prefix size.
