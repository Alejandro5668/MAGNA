# Design: Multi-agent task context graph (LangGraph + create_agent)

## Technical Approach

One new module, `aicli/services/task_graph.py`, owns a compiled `StateGraph` with 4
nodes. `START` fans out to 3 specialists in a single superstep and they fan back into
`Sintetizador`. Only the Detective uses LangChain (`create_agent` ReAct loop with a
`ChatAnthropic` instance); Historiador, Vigía and Sintetizador stay on the plain
Anthropic SDK through `indexer._call_claude`, matching changes 1-3. `task.py` loses
both helpers and gains one call to `run_task_graph(...)` placed after `evidence_summary`
exists. The graph and the Detective agent are lazy module-level singletons behind
function-local imports, mirroring `task.py:40`'s lazy `embeddings` import.

Verification honesty: `langchain`/`langgraph` are not installed in this repo's `.venv`
yet and this phase had no live-doc access, so the two `create_agent` mechanisms below
are designed against the LangChain v1 API as documented in `exploration.md` plus known
v1 shapes. Both carry an in-design fallback and an explicit empirical check in apply's
smoke task — they are not assumed correct.

## Architecture Decisions

### Decision: cache-control pass-through into `create_agent`

| Option | Tradeoff | Verdict |
|---|---|---|
| A `system_prompt="…"` | v1 types it `str`; a string cannot carry `cache_control` → silent `ai-prompt-caching` regression | Rejected |
| B No `system_prompt`; first input message is `SystemMessage(content=[{…,"cache_control":{"type":"ephemeral"}}])` | langchain-anthropic's documented caching recipe: leading `SystemMessage` is lifted into the request's `system` array and dict blocks pass through verbatim | **Chosen** |
| C `AnthropicPromptCachingMiddleware` | Automatic, but the library picks the breakpoint; we lose the exact block boundary change 1 specified | Fallback |
| D Drop caching in the Detective | Certain regression | Last resort, would need a spec amendment |

`_system_blocks(candidates, project_context)` reproduces `task.py:63-72` byte-for-byte,
so the cached prefix is unchanged; only its transport changes.

```python
result = _get_detective().invoke(
    {"messages": [SystemMessage(content=_system_blocks(...)),
                  HumanMessage(content=user_prompt)]},
    config={"recursion_limit": 12},
)
```

Observability (change 1's requirement) moves to the final `AIMessage`:
`usage_metadata["input_token_details"]` → `cache_read` / `cache_creation`, logged in
`task.py`'s existing `logging.info` format. Bonus, not a regression: inside one ReAct
loop turns 2..N re-send the same prefix, so they are cache reads.

**Risk carried to verify**: if B does not survive `create_agent`'s message handling,
C is used; if neither works, the delta spec's non-regression scenario fails and the
change must be re-scoped. Verify must assert `cache_read_input_tokens > 0` empirically,
not by reading code.

### Decision: Detective termination without per-turn forced `tool_choice`

Forcing `tool_choice` every turn (change 2's pattern) makes the loop non-terminating,
so termination comes from a terminal structured response instead.

- Iterative tools (`tool_choice` left `auto`): `leer_doc_modulo(name: str) -> str`
  (reads `Module.content_path`, 2000-char cap) and `buscar_en_codigo(pattern: str) -> str`
  (bounded literal scan of the target repo, ≤40 hits).
- Terminal: `response_format=ToolStrategy(SeleccionarModulos)` where
  `class SeleccionarModulos(BaseModel): modules: list[str]`. The model calling it ends
  the loop; the parsed object surfaces at `state["structured_response"]`.
- `create_agent` returns a `CompiledStateGraph`, **not** raw Anthropic blocks, so
  `indexer._extract_tool_input` does **not** apply here. Extraction is defensive and
  covers the fallback mechanism too:

```python
sel = result.get("structured_response")
names = list(sel.modules) if sel else _scan_last_tool_call(result["messages"], "seleccionar_modulos")
return [m for m in modules if m.name in names] if names else candidates
```

`_scan_last_tool_call` walks `result["messages"]` in reverse for an `AIMessage.tool_calls`
entry named `seleccionar_modulos` and reads `call["args"]["modules"]`. That single helper
also implements fallback mechanism B (plain terminal tool returning a sentinel) if
`ToolStrategy` is unavailable in the pinned version — no second code path needed.
Exhausting `recursion_limit` degrades to the prefilter candidates; it never raises.

### Decision: `ChatAnthropic` instance, not the `"anthropic:claude-sonnet-5"` string

`ChatAnthropic(model="claude-sonnet-5", max_tokens=4000)` (no `thinking`) keeps
the model id explicit and removes `init_chat_model`'s dynamic provider import —
the exact mechanism that breaks under PyInstaller. Rejected: the provider
string, which hides the constructor. `thinking={"type": "adaptive"}` was
dropped from this instance specifically (not from other Anthropic calls in the
repo): `ToolStrategy`'s forced `tool_choice="any"` is silently discarded by
`langchain_anthropic` whenever `thinking` is enabled, undermining the
Detective's loop-termination guarantee — see the corrective fix that removed
it from `task_graph.py`.

### Decision: prefilter runs in `run_task_graph`, not in a 5th node

Detective and Vigía both need the same candidate set, and Vigía runs in parallel with
Detective so it cannot wait for the final selection. `run_task_graph` computes
`candidates = query_modules(...)` plus the `--file` union (today's `task.py:42-45`) once
and seeds the state. Rejected: a `START → prefilter → fan-out` node (adds a superstep for
non-LLM work) and per-node `query_modules` calls (double Chroma work, divergent sets).

### Decision: Detective node is a wrapper function, not the agent embedded directly

The agent's state is `{"messages": …}`; ours is keyed per specialist, so a mapping
wrapper is required anyway. Keeping `agent.invoke()` inside a plain function node also
keeps it on the node's own call stack, which is what makes the `ContextVar` scope used by
the tools (`_SCOPE`: `project_id` + `candidates` + repo root, set at node entry, reset in
`finally`) reliable. Fallback if that proves flaky under LangGraph's executor: build the
agent inside the node (cost is a few ms; the *outer* graph singleton is the one the
proposal mandated).

### Decision: Vigía maps tests by content scan, never by filename

Verified in `tests/test_commands.py` (lines 76/91/99): one test file covers 7+ unrelated
modules. Discovery keeps files matching `test_*`/`*_test.*`/`*.test.*`/`*.spec.*` or living
under a `tests`/`__tests__`/`spec` segment, skipping `.git`, `.venv`, `node_modules`,
`dist`, `build`, `__pycache__`, `.codegraph`; capped at 400 files and 200 KB each. A
module matches when a multi-segment form of `Module.file_path` appears (`aicli/commands/task`,
`aicli.commands.task`, `commands/task`); the bare stem counts only on an import-like line
(`import`, `from`, `require(`, `jest.mock(`, `patch("`) and never for stems in
`GENERIC_STEMS = {index, utils, main, app, init, types, const, helpers}` or shorter than 4
chars. Evidence is `(file, line_no, line)` so the synthesizer can be discounted.

## Data Flow

```
run_task_graph(task_desc, modules, file, project_context, evidence)
   │  query_modules(...) + --file union  →  candidates
   ▼
 START ──┬──► detective   (create_agent ReAct: leer_doc_modulo / buscar_en_codigo
         │                 → terminal seleccionar_modulos)   → relevant
         ├──► historiador (load_tickets() → keyword overlap top-3 → 1 SDK call) → precedent
         └──► vigia       (discover tests → content scan → 1 SDK call)          → coverage
                                   │ (all three, one superstep)
                                   ▼
                              sintetizador (1 SDK call) → brief
                                   │
                            (relevant, brief) → task.py
```

Every node is wrapped in `try/except` → empty section + `logging.warning`; a failing
specialist degrades its section, never the run. Detective failure degrades to
`candidates`. Sintetizador failure degrades to a deterministic locally-assembled brief.

## File Changes

| File | Action | Description |
|---|---|---|
| `aicli/services/task_graph.py` | Create | State, 4 nodes, tools, singletons, `run_task_graph` (~330 lines) |
| `aicli/commands/task.py` | Modify | Delete `_detect_relevant_modules`+`_generate_task_brief` (37-146); one invoke at the old 324-327 site; `MODULE_SELECTION_TOOL` moves to `task_graph.py` |
| `aicli/commands/graph_selftest.py` | Create | Hidden frozen-exe probe, mirrors `embed_selftest.py` |
| `main.py` | Modify | Import + `app.add_typer(graph_selftest.app, name="graph-selftest", hidden=True)` |
| `ctx.spec` | Modify | LangChain/LangGraph `datas`/`copy_metadata`/`hiddenimports` |
| `scripts/verify_frozen.ps1` | Modify | Renumber to 6 steps; new `graph-selftest` gate |
| `requirements.txt` | Modify | `langgraph`, `langchain`, `langchain-anthropic` (pins re-verified at `sdd-tasks`) |
| `tests/test_task_graph.py` | Create | ~280 lines |

## Interfaces / Contracts

```python
class TaskGraphState(TypedDict, total=False):
    task_desc: str; file: str | None; evidence: str | None
    project_context: str | None; project_id: int
    modules: list[Module]; candidates: list[Module]   # inputs
    relevant: list[Module]; precedent: str; coverage: str; brief: str   # one key per node

def run_task_graph(task_desc: str, modules: list[Module], file: str | None = None,
                   project_context: str | None = None, evidence: str | None = None,
                   ) -> tuple[list[Module], str]: ...

def _buscar_precedentes(task_desc: str, tickets: dict, top_k: int = 3) -> list[dict]
def _historiador(state: TaskGraphState) -> dict          # {"precedent": str}
def _discover_test_files(root: Path, limit: int = 400) -> list[Path]
def _scan_coverage(test_files: list[Path], modules: list[Module]) -> dict[str, list[tuple[str, int, str]]]
def _vigia(state: TaskGraphState) -> dict                # {"coverage": str}
def _sintetizador(state: TaskGraphState) -> dict         # {"brief": str}
def get_graph()                                          # lazy module-level singleton
```

Separate state keys → no reducer. No checkpointer, so detached `Module` instances travel
through state unserialized, exactly as `task.py` already passes them today.

`_buscar_precedentes`: lowercase + strip accents, split on non-alphanumerics, drop Spanish
stopwords and tokens shorter than 4, score each ticket by token overlap against
`descripcion` + every round's `motivo_reapertura`/`memoria`, keep positive-score top-3. An
empty corpus or zero hits skips the LLM call entirely and returns
`"Sin precedentes en el historial de tickets."`; likewise Vigía returns
`"Sin cobertura de tests detectada."` (user decision: advisory only, never blocks).

Sintetizador prompt (model `MODEL_BY_OPERATION["task_brief"]`, `max_tokens=700`): the
existing `_generate_task_brief` prompt plus `Precedentes de tickets anteriores:` and
`Cobertura de tests detectada:` sections and one extra instruction — *"Si una sección viene
vacía, ignorala en silencio; no la menciones. Citá el ticket concreto cuando exista y nombrá
los tests que cubren, o el hueco de cobertura."* Max 10 lines (up from 8). Output stays a
plain string.

## Integration into `_execute_task`

The ~120-line attachment/evidence section (today `201-322`) keeps its content
**byte-identical and in the same relative order** — the proposal's finding holds: the small
call site moves, the big block does not get hoisted. Concretely: `190-199` (status +
`_detect_relevant_modules` + `if not relevant` + `--file` union) is deleted, and `324-325`
becomes:

```python
with magna_status(console, "Analizando tarea (detective · historiador · vigía)..."):
    relevant, brief = run_task_graph(task_desc, modules, file, project_context, evidence_summary)

if not relevant:
    relevant = modules
if file:                                   # guarantee union — stays OUTSIDE the graph
    file_module = next((m for m in modules if m.file_path == file), None)
    if file_module and file_module not in relevant:
        relevant = [file_module] + relevant
```

Both `--file` unions are preserved: the *candidate* union moves into `run_task_graph`
(was `task.py:42-45`), the *guarantee* union stays in `task.py` (was `196-199`), so no
graph bug can drop the pin. `magna_task_plan(console, relevant, brief)`,
`build_context(relevant, project_path=path)`, the receipt block and `launch_claude(...)`
are untouched.

## PyInstaller Packaging

```python
datas += collect_data_files('langchain')  + collect_data_files('langchain_core')
datas += collect_data_files('langgraph')
datas += copy_metadata('langchain') + copy_metadata('langchain-core')
datas += copy_metadata('langchain-anthropic') + copy_metadata('langgraph') + copy_metadata('anthropic')
hiddenimports += collect_submodules('langchain') + collect_submodules('langchain_core')
hiddenimports += collect_submodules('langchain_anthropic') + collect_submodules('langgraph')
hiddenimports += ['langchain_anthropic.chat_models', 'langgraph.graph', 'langgraph.prebuilt']
```

`copy_metadata` is not optional: langchain-core resolves package versions via
`importlib.metadata` at import time (the `#15386`/`#8055` failure class). `collect_submodules`
covers the dynamic-import provider resolution PyInstaller's static `Analysis` cannot see.

`aicli/commands/graph_selftest.py` mirrors `embed_selftest.py` exactly: no
`ANTHROPIC_API_KEY`, no network. It (1) constructs `ChatAnthropic(model="claude-sonnet-5",
api_key="selftest-unused")` to prove the provider import/init path, (2) builds the graph via
the injectable seam `_build_graph(model=<scripted fake>, single_shot=<stub>)`, (3) invokes it
cold on a stub state, (4) prints `langgraph version`, `nodes: detective,historiador,vigia,
sintetizador` and `OK`, exiting 1 on any exception. `scripts/verify_frozen.ps1` gains it as a
step between the warm `embed-selftest` and `status` (renumbering `[1/5]`→`[1/6]`), asserting
exit 0 and the `OK` line — blocking, same shape as change 3.

## Testing Strategy

| Layer | What | Approach |
|---|---|---|
| Unit — Detective | System message carries the `cache_control` block; 2 lookup tools bound; loop ends on the terminal call; names filtered against `modules`; no terminal call → degrades to candidates | Inject a ~20-line `_ScriptedChatModel(BaseChatModel)` (queued `AIMessage`s with `tool_calls`; `bind_tools` returns self) via `_build_graph(model=…)`. **Mock at the `BaseChatModel` seam, not `anthropic.Anthropic`** — `ChatAnthropic` builds its client at init and parses SDK objects itself, so SDK-level patching would force us to emulate LangChain's parsing |
| Unit — Historiador | Accent/stopword normalization, `motivo_reapertura` hit, empty corpus skips the LLM call | Pure Python over a fixture dict; `@patch("aicli.services.task_graph._call_claude")` |
| Unit — Vigía | Multi-module test file maps to both; generic stem rejected without a multi-segment match; ignored dirs skipped | `tmp_path` fake repo; `@patch(... _call_claude)` |
| Unit — Sintetizador | Prompt carries all 3 sections + evidence; LLM failure → deterministic fallback brief | `@patch(... _call_claude)` |
| Integration — wiring | All 3 specialists run from `START`; Sintetizador runs once and sees all 3 outputs; one specialist raising still yields a brief; graph compiled once | Patch the 4 node functions with recorders; assert `get_graph() is get_graph()` |
| Integration — `task.py` | One `run_task_graph` call, receiving non-`None` `evidence` when an image was analyzed; `--file` union still applied; `build_context` receives `relevant` | `@patch("aicli.commands.task.run_task_graph")` |
| Frozen | Imports, compile, cold invoke inside `MAGNA.exe` | `graph-selftest` + `verify_frozen.ps1` step 5/6 |

No test constructs a real client or touches the network, per this project's convention.

## Threat Matrix

N/A — no routing, git/PR automation, commit/push state, executable-file classification,
or subprocess composition changes. `launch_claude`'s subprocess boundary is untouched.
The one new boundary is Vigía's read-only filesystem traversal of the target repo,
bounded by the ignore list, the 400-file cap and the 200 KB per-file cap defined above;
it never executes, writes or follows symlinks outside the project root.

## Migration / Rollout

No migration. Pure code + dependency change: the graph reads existing stores read-only and
persists nothing new (no schema, no on-disk format, no `~/.mycontext` writes beyond the
pre-existing receipt file). Rollback = `git revert` + drop the three deps from
`requirements.txt` + revert `ctx.spec`. No intermediate state can survive a revert.

**Line estimate (informational — `size:exception` already accepted)**: ~700 additions
(`task_graph.py` 330, tests 280, selftest 60, spec/script/requirements 31) + ~110 deletions
in `task.py` ≈ **780-830 changed lines**.

## Open Questions

- [ ] Empirical: does a leading `SystemMessage` with dict content blocks reach Anthropic's
      `system` array with `cache_control` intact through `create_agent`? (apply smoke task;
      verify asserts `cache_read > 0`)
- [ ] Empirical: does `ToolStrategy` terminate the ReAct loop and populate
      `structured_response`, or is the plain-terminal-tool fallback needed?
- [ ] Empirical: does the tools' `ContextVar` scope survive LangGraph's node executor, or
      must the Detective agent be built per invocation?
