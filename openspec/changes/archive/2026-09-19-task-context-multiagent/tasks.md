# Tasks: Multi-agent task context graph (LangGraph + create_agent)

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | ~950 (design's 780-830 + ~275 test-fixup lines in Phase 8) |
| 400-line budget risk | High |
| Chained PRs recommended | No — `size:exception` already accepted (state.yaml) |
| Suggested split | Single PR |
| Delivery strategy | single-pr |
| Chain strategy | size-exception |

Decision needed before apply: Yes
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | PR | Focused test command | Runtime harness | Rollback boundary |
|---|---|---|---|---|---|
| 1 | task_graph.py + task.py wiring + packaging + test fixups | PR 1 | `.venv\Scripts\python.exe -m pytest tests/test_task_graph.py -v` | `dist\MAGNA.exe graph-selftest` (Phase 7, blocking) | `git revert`; drop 3 deps; revert `ctx.spec` |

## Phase 0: Dependency Gate (BLOCKING)
- [x] 0.1 Install `langgraph`/`langchain`/`langchain-anthropic` in `.venv`; clean import of all three. Incompatible with this repo's Python → STOP, report, do not proceed.
- [x] 0.2 Pin resolved versions in `requirements.txt`.

## Phase 1: Foundation
- [x] 1.1 RED (`test_task_graph.py`): `get_graph() is get_graph()`.
- [x] 1.2 GREEN: `task_graph.py` — `TaskGraphState`, `_SCOPE` ContextVar, lazy `get_graph()`.

## Phase 2: Detective node
- [x] 2.1 Add `_ScriptedChatModel(BaseChatModel)` test double.
- [x] 2.2 RED→GREEN: leading `SystemMessage` carries `cache_control`, matches `_system_blocks` byte-for-byte.
- [x] 2.3 RED→GREEN: `leer_doc_modulo`/`buscar_en_codigo` bound, unforced `tool_choice`.
- [x] 2.4 RED→GREEN: terminal `SeleccionarModulos` ends loop; names filtered against `candidates`.
- [x] 2.5 RED→GREEN: no terminal call within `recursion_limit` → degrades to `candidates`, never raises.
- [x] 2.6 Empirical — cache: 2 scripted calls, identical prefix; assert `cache_read_input_tokens > 0` on call 2. Fail → `AnthropicPromptCachingMiddleware` fallback. **RESULT: PRIMARY mechanism (leading SystemMessage with dict cache_control blocks) works — confirmed empirically both via a standalone probe script and `test_cache_read_tokens_positive_on_second_scripted_call`. No fallback needed.**
- [x] 2.7 Empirical — termination: scripted terminal call; assert `result["structured_response"]` populated. Fail → `_scan_last_tool_call` fallback, same names recovered. **RESULT: PRIMARY mechanism (`ToolStrategy(seleccionar_modulos)`) works — `result["structured_response"]` is populated directly as a parsed pydantic object, no `json.loads`. Confirmed via probe + `test_structured_response_populated_after_terminal_call`. `_scan_last_tool_call` is implemented and kept as a defensive fallback (also exercises the recursion-limit-exhaustion path) but was never needed for the happy path. Tool name resolution note: `ToolStrategy`'s default naming derives the tool name from the Python class `__name__` (confirmed via source read of `langchain.agents.structured_output._SchemaSpec`), so the terminal-tool class was named `seleccionar_modulos` (snake_case) instead of the PascalCase `SeleccionarModulos` sketched in design.md, to make the produced tool name match the spec's literal `seleccionar_modulos` naming exactly — a naming-only deviation, no behavior change.**
- [x] 2.8 Empirical — ContextVar: tool called mid-loop; assert it reads the `_SCOPE` set at node entry, not stale. Fail → build agent inside `_detective(state)`, not singleton. **RESULT: PRIMARY mechanism (module-level `_SCOPE` ContextVar set at node entry, reset in `finally`) works — confirmed via probe script (including a real `StateGraph` fan-out with a concurrently-different-valued sibling node to rule out cross-node leakage) and `test_contextvar_scope_read_correctly_by_tool_mid_loop`. No fallback needed; the singleton `_get_detective_agent()` is kept.**

## Phase 3: Historiador, Vigía, Sintetizador
- [x] 3.1 RED→GREEN `_buscar_precedentes`: accent/stopword normalization, `motivo_reapertura` hit, empty corpus skips LLM call.
- [x] 3.2 RED→GREEN `_historiador(state)` (`@patch(..._call_claude)`).
- [x] 3.3 RED→GREEN `_discover_test_files`/`_scan_coverage`: multi-module file maps both; generic stem rejected; ignored dirs skipped.
- [x] 3.4 RED→GREEN `_vigia(state)` (`@patch(..._call_claude)`).
- [x] 3.5 RED→GREEN `_sintetizador(state)`: prompt carries 3 sections + evidence; LLM failure → deterministic fallback brief.

## Phase 4: Graph wiring & run_task_graph
- [x] 4.1 RED→GREEN: `START` fans to all 3 specialists one superstep; Sintetizador runs once after (recorder-patched nodes).
- [x] 4.2 RED→GREEN: one specialist raising still yields non-empty brief.
- [x] 4.3 RED→GREEN: `run_task_graph` builds `candidates` via `query_modules`+`--file` union — migrate assertions from `test_module_prefilter.py:258-384` here.
- [x] 4.4 GREEN: wire `add_edge`/`add_node`; implement `run_task_graph()` per design's Interfaces.

## Phase 5: task.py integration
- [x] 5.1 Delete `_detect_relevant_modules`+`_generate_task_brief`+`MODULE_SELECTION_TOOL` (`task.py:20-146`); replace call sites 190-199/324-327 with design's exact `run_task_graph(...)` block; keep the guarantee `--file` union in `task.py`.
- [x] 5.2 RED→GREEN integration test (`@patch("aicli.commands.task.run_task_graph")`): non-`None` evidence passed, `--file` union still applied, `build_context` receives `relevant`.

## Phase 6: graph-selftest
- [x] 6.1 Create `aicli/commands/graph_selftest.py` mirroring `embed_selftest.py`: `_build_graph(model=<scripted>, single_shot=<stub>)`, cold invoke, print version/`nodes:`/`OK`, exit 1 on exception.
- [x] 6.2 Register in `main.py`: `app.add_typer(graph_selftest.app, name="graph-selftest", hidden=True)`.

## Phase 7: Packaging (BLOCKING)
- [x] 7.1 `ctx.spec`: add `datas`/`copy_metadata`/`hiddenimports` per design's PyInstaller block.
- [x] 7.2 `verify_frozen.ps1`: renumber `[1/5]`→`[1/6]`, insert `graph-selftest` step (exit 0 + `OK`) between warm embed-selftest and `status`.
- [x] 7.3 Run `verify_frozen.ps1` end to end — must PASS all 6 steps. **RESULT: PASS — all 6 steps exited 0. [1/6] pip install OK. [2/6] PyInstaller build OK (langchain/langchain-core/langchain-anthropic/langgraph/anthropic metadata+submodules bundled cleanly; only pre-existing/unrelated warnings: `posthog` hidden-import-not-found and `langchain.mcp`/`chromadb.server.fastapi` optional-submodule-not-found, none of which block or are exercised by this change's code paths). [3/6] cold `embed-selftest`: ONNX model downloaded (79.3M), `top-1: auth`, `OK`. [4/6] warm `embed-selftest`: `top-1: auth`, `OK`, no re-download. [5/6] `graph-selftest` (NEW, this change's blocking gate): `langgraph version: 1.2.11`, `nodes: detective,historiador,vigia,sintetizador`, `OK`, exit 0 — confirms `create_agent`/`ChatAnthropic`/`StateGraph` import, compile, and cold-invoke cleanly inside the real frozen `MAGNA.exe`, no network, no missing-module errors. [6/6] `status` non-regression: exits 0 (prints the expected "directory not registered" notice for the fresh temp HOME, which is correct behavior, not a failure). Final line: `verify_frozen: PASS - all 6 steps exited 0, cold+warm both top-1 auth, warm had no download line, graph-selftest OK`.**

## Phase 8: Regression fixups
- [x] 8.1 `test_commands.py:92` — drop `_detect_relevant_modules` from the import.
- [x] 8.2 `test_prompt_caching.py` — delete `PromptCachingSystemBlockTestCase`/`CacheUsageObservabilityTestCase`/`ContractPreservationTestCase` (lines 68-212, call the deleted function); keep the rest.
- [x] 8.3 `test_module_prefilter.py` — delete `TaskWiringTestCase`/`CachedListingVariesWithTaskDescTestCase`/`ExistingFixtureNoOpRegressionTestCase` (lines 258-384); keep the rest.
- [x] 8.4 `.venv\Scripts\python.exe -m pytest tests/ -v` — full suite green, no stale references. **RESULT: `pytest tests/ --ignore=tests/test_commands.py -v` → 130 passed, 0 failed (includes the new `tests/test_task_graph.py` with 36 tests). `tests/test_commands.py` is a standalone script (not patched into pytest's normal per-test isolation — a module-level `sys.exit(1)` on internal failure that crashes pytest's collection for the WHOLE run via INTERNALERROR when run through `pytest tests/` unfiltered) — run directly via `python tests/test_commands.py`, it reports 19/23 passing; the 4 failures (`ImportError: cannot import name 'StatusScreen'/'_MENU'/'_HELP_ROWS' from 'aicli.tui.app'`, `AttributeError: ... no attribute '_dispatch_tui'`) are pre-existing and unrelated to this change — confirmed via `git status --short aicli/tui/app.py` showing that file untouched/unmodified by this change or by me at all; they stem from other in-flight TUI work already present in this working tree before this SDD run started (dashboard-story-switcher / ticket-panel-nav changes). The one line this change owns in that file (`cmd: task — importa correctamente`) passes.**
