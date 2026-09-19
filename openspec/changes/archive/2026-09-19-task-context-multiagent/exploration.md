# Exploration: task-context-multiagent (StateGraph + create_agent multi-agent brief generation)

## Current State

`aicli/commands/task.py:37-108` — `_detect_relevant_modules` already includes changes 1-3: calls `query_modules()` (Chroma top-N prefilter from `aicli/services/embeddings.py:78-92`), builds a cached `system` array (`cache_control: ephemeral`), forces `tool_choice` against `MODULE_SELECTION_TOOL`, single-shot Anthropic call, returns filtered `list[Module]`.

`aicli/commands/task.py:111-146` — `_generate_task_brief` is single-shot, no tools/caching, returns a plain string.

Call order in `_execute_task` (`task.py:149-356`): `_detect_relevant_modules` (line 191) → image/Jira attachment analysis building `evidence_summary` (lines 201-322) → `_generate_task_brief` (line 325) → `magna_task_plan` (327) → `build_context(relevant, ...)` (329) → `launch_claude(...)` (346-355). **Handoff confirmed unchanged**: `brief` (str) lands verbatim under `# Plan de implementación` in `session_context.md` via `caller.py:198-199`; `relevant` (`list[Module]`) feeds `build_context()` separately. A multi-agent replacement only needs to still produce these two shapes at those two call sites.

## `aicli/services/tickets.py` (Historiador de Jira)

Per-ticket JSON at `~/.mycontext/tickets/{id}.json`; `rondas` carry `archivos_tocados`, `motivo_reapertura` (reopen signal), `memoria`. `format_history()` (lines 161-198) is per-ticket-id only — **no cross-ticket similarity search exists**. `load_tickets()` (119-133) returns the full corpus to search over. Reusing `embeddings.py`'s Chroma pattern for semantic ticket search is plausible but needs a **new collection** (existing `project_{id}` collection is Module-scoped by `Module.id`) — real new design work, not free reuse. Cheaper fallback: keyword/substring overlap over `descripcion`/`motivo_reapertura`.

## Test coverage mapping (Vigía de Tests)

No existing coverage-mapping utility. `tests/` naming is **not** a reliable 1:1 convention: `test_commands.py` alone smoke-tests 7+ unrelated command modules (`test_cmd_init`, `test_cmd_task`, `test_cmd_sync`, etc., verified at lines 76/91/99), which directly disproves naive filename-pattern matching. Cheapest real signal: grep test files for `from aicli.X import` / `import aicli.X` to build an actual import-based module→test map.

## LangGraph / LangChain (live-doc verified this session)

- `langgraph` current ~1.2.x. `docs.langchain.com/oss/python/langgraph/graph-api` confirms `StateGraph(TypedDict/dataclass/Pydantic)` → `add_node`/`add_edge`/`add_conditional_edges`/`compile()`. **Fan-out/fan-in for a fixed 3-node set**: plain multiple `add_edge(START, node)` calls fan out automatically in one superstep; multiple edges converging on one node fan back in — `Send` (dynamic/list-driven fan-out) is unnecessary here since Detective/Historiador/Vigía are fixed, not data-driven. Recommend separate state keys per specialist node (no reducer needed) over shared-key + reducer.
- `create_agent`: confirmed `from langchain.agents import create_agent` (current LangChain v1 GA, not `langchain_classic`, not the older `langgraph.prebuilt.create_react_agent`). Params: `model` (string `"anthropic:claude-sonnet-5"` or `BaseChatModel`), `tools`, `system_prompt`, plus optional `middleware`/`state_schema`/etc. Returns a `CompiledStateGraph`, explicitly documented as embeddable as a subgraph node in another `StateGraph` ("particularly useful for building multi-agent systems") — no wrapping needed. Still recommend one explicit smoke-test task since no byte-identical example exists for this exact 3-parallel-plus-agent-subgraph shape.
- Needs `langchain-anthropic` alongside `langgraph`+`langchain`.

## PyInstaller packaging impact

Confirmed real risk via search (GitHub `pyinstaller/pyinstaller#8055`, `langchain-ai/langchain#15386`): LangChain has a documented history of frozen-exe `FileNotFoundError`s (external template/data files) and import failures from dynamic imports PyInstaller's static `Analysis` can't discover. Structurally the same class of problem `ctx.spec:1-23` already solved for `chromadb`/`onnxruntime` (`collect_data_files`, `copy_metadata`, `collect_dynamic_libs`, `collect_submodules`, explicit hidden-imports). Recommend the same blocking frozen-exe verification gate `module-semantic-prefilter`'s proposal used (`openspec/changes/archive/2026-09-19-module-semantic-prefilter/proposal.md` — Risks table + Success Criteria "frozen exe runs `ctx task` end to end").

## Where this wires into `_execute_task`

Replace the two calls at `task.py:191` and `task.py:325` with one `graph.invoke(...)`, exposing at minimum the Detective's `list[Module]` (→ `build_context()` at 329, `--file` pin logic 196-199) and Sintetizador's brief string (→ `magna_task_plan()` 327, `launch_claude()` 352). Historiador needs the full `load_tickets()` corpus (new access, not `ticket_history`'s per-ticket text alone).

## Recommendation for sdd-propose

1. Static edges for fan-out/fan-in (not `Send`), separate state keys per node.
2. `create_agent` embedded directly as a node — budget one smoke-test task.
3. Historiador and Vigía: single-shot, no `create_agent` — no concrete reason found requiring multi-turn iteration for either.
4. Vigía: import-scan signal, explicitly reject filename-pattern matching.
5. Historiador: start with keyword overlap; flag Chroma-based ticket search as a stretch option, not assumed reuse.
6. Apply the same blocking PyInstaller gate as `module-semantic-prefilter`.

## Risks

- PyInstaller/frozen-exe compatibility for `langchain`+`langgraph`+`langchain-anthropic` (confirmed real, same class as change 3's chromadb/onnxruntime work).
- `create_agent`-as-subgraph-node composition documented but unverified against this exact shape — needs early smoke test in apply.
- Reintroduces provider-abstraction dependency DEC-080 previously rejected — `state.yaml` frames this as accepted/deliberate; propose must restate plainly.
- Historiador's cross-ticket similarity search has zero existing implementation — real new logic either way.
- No reliable existing test-coverage signal in this codebase.
- Exact `langgraph`/`langchain`/`langchain-anthropic` pins were found via web search, not verified against a local lockfile (not yet installed here) — re-verify pins at `sdd-tasks` time.

## Ready for Proposal

Yes — all 7 investigation points answered with file:line/doc citations; `pre_decided_architecture` in `state.yaml` treated as final and not re-litigated.
