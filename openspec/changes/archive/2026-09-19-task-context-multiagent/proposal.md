# Proposal: Multi-agent task context graph (LangGraph + create_agent)

## Intent

`ctx task` builds its context from two blind, sequential single-shot calls
(`_detect_relevant_modules` → `_generate_task_brief`, `task.py:37-146`). The brief is
written from module names alone: it does not know whether this bug already happened
before (`~/.mycontext/tickets/` holds `motivo_reapertura` per round, never read
cross-ticket), nor whether the modules it points at have any test coverage. Replace
both calls with one `StateGraph` — three parallel specialists feeding one synthesizer —
so the plan Claude Code reads first carries precedent and coverage, not just a file list.

## Scope

### In Scope
- `aicli/services/task_graph.py` (new): `StateGraph` + 4 nodes, compiled once per process.
  - **Detective** — `create_agent` ReAct loop; absorbs today's Chroma prefilter, `--file`
    candidate union, module listing, cached system prefix. Outputs `list[Module]`.
  - **Historiador** — keyword/substring overlap over `descripcion`/`motivo_reapertura`
    across `load_tickets()`, then one single-shot call. Outputs precedent text.
  - **Vigía** — discovers test files by path/name convention in the target repo, scans
    their contents for each candidate module's path stem, then one single-shot call.
    Outputs coverage/gap text.
  - **Sintetizador** — reconciles all three into the brief string.
- `task.py`: delete both helpers; one `graph.invoke()` at today's `_generate_task_brief`
  site (line 325), after the evidence block, so `evidence_summary` reaches the graph.
- `requirements.txt` (`langgraph`, `langchain`, `langchain-anthropic`), `ctx.spec`,
  a hidden `graph-selftest` command, and a 6th step in `scripts/verify_frozen.ps1`.

### Out of Scope
- Chroma-backed semantic ticket search (new collection + upsert sites = its own change).
- `create_agent` for Historiador/Vigía — no iteration need found.
- Re-litigating the pre-decided architecture (`state.yaml`), or changing `caller.py`,
  `build_context()`, `magna_task_plan`, or the `session_context.md` format.

## Capabilities

### New Capabilities
- `ai-task-graph`: parallel specialist orchestration, per-node degradation, synthesis.

### Modified Capabilities
- `ai-structured-output`: *Forced Tool Choice for Structured Calls* cannot hold inside a
  ReAct loop (forcing every turn prevents termination). Module list becomes a terminal
  structured response. Delta spec required.
- `ai-prompt-caching`: the cached `cache_control: ephemeral` prefix must survive
  `create_agent`'s `system_prompt`. Delta spec + explicit non-regression scenario.
- `ai-module-prefilter`: *Semantic Top-N Prefilter* and *File-pinned module is always
  included* relocate into the Detective node. Delta spec.

## Approach

| Decision | Choice | Rationale |
|---|---|---|
| Fan-out/fan-in | Static `add_edge(START, n)` ×3 → Sintetizador; separate state key per node | Specialists are fixed, not data-driven — `Send` buys nothing; separate keys need no reducer |
| Detective | `create_agent` as an embedded subgraph node | Only node with real multi-turn value (read a doc → decide if another lookup is needed) |
| Historiador retrieval | Keyword overlap, not Chroma | Retrieval is only a prefilter — the LLM still judges, so a recall miss degrades to "no precedent". Chroma needs a new collection + upserts at every ticket write = a second change-3-sized unit |
| Vigía signal | Path/name convention identifies *test files*; content scan of module path stems maps them to modules | `tests/test_commands.py` smoke-tests 7+ unrelated modules (verified 76/91/99) — filename-to-module matching is provably wrong here. Generalized beyond exploration's `from aicli.X` idea: `Module.file_path` points into an arbitrary target repo, not MAGNA |
| Graph lifetime | Lazy module-level singleton behind a function-local import | Mirrors `task.py:40`'s lazy `embeddings` import; `main.py` imports every command at boot, so a top-level `langchain` import would tax `ctx status` and the TUI |
| `--file` pin | Candidate union moves into Detective; the guarantee union at `task.py:196-199` stays outside the graph, untouched | A graph bug can never drop the pin |
| Packaging | Blocking, reusing change 3's script | Different failure class, not a repeat: LangChain resolves providers by *dynamic import* at runtime — invisible to PyInstaller's static `Analysis`, and it fails only in the frozen exe, on `ctx task`, the flagship command |

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `aicli/services/task_graph.py` | New | Graph, 4 nodes, state, fallbacks (~300 lines) |
| `aicli/commands/task.py:37-146,190-199,324-327` | Modified | Both helpers deleted; single invoke, moved below evidence |
| `aicli/commands/graph_selftest.py`, `main.py` | New/Modified | Frozen-exe probe, mirrors `embed_selftest.py` |
| `ctx.spec`, `requirements.txt`, `scripts/verify_frozen.ps1` | Modified | Bundling + blocking gate step 6 |
| `tests/test_task_graph.py` | New | Graph shape, degradation, pin, retrieval/scan units |

## Dependency tradeoff (stated plainly)

`langchain` + `langchain-anthropic` reintroduce the multi-provider abstraction layer
**DEC-080 deliberately rejected** for MAGNA. This is the user's explicit, informed
choice — same reasoning already accepted for change 3's Chroma decision — pulled in
**only** for the Detective node's `create_agent`. `langgraph` alone (lean, no provider
abstraction) carries the other three nodes. A future reader should read this as a
scoped exception to MAGNA's minimal-dependency philosophy, not as scope creep.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `create_agent`'s `system_prompt` drops `cache_control` → silently regresses change 1 | High | Design must pick the pass-through (structured `SystemMessage` blocks or middleware); verify against the existing cache-read log requirement |
| LangChain dynamic imports break the frozen exe | High | Blocking `graph-selftest` + `verify_frozen.ps1` step 6 |
| `create_agent`-as-subgraph-node unverified for this exact shape | Med | Dedicated early smoke-test task before node logic |
| Vigía false positives on generic stems (`index`, `utils`) | Med | Prefer import-like lines + longest path-segment match; node reports file/line evidence so noise is discountable |
| One slow/failing specialist blocks the brief | Med | Per-node try/except → empty section; Sintetizador must produce a brief from whatever arrived |
| Three parallel calls raise `ctx task` latency/cost | Med | Parallel supersteps cap wall-clock at the slowest node; measure in verify |
| Exe size/build time grows | Low | Accepted; UPX excludes already in `ctx.spec` |
| Pins found via web search, not a local lockfile | Med | Re-verify at `sdd-tasks` |

## Rollback Plan

Pure code + dependency change. No schema, no migration, no on-disk format change — the
graph reads existing stores read-only and writes nothing new. Rollback = `git revert` +
drop the three deps from `requirements.txt` + revert `ctx.spec`; `~/.mycontext/` is
untouched. No intermediate state can be left behind, because nothing persists.

## Success Criteria

- [ ] One `graph.invoke()` replaces both calls; `brief` (str) still lands under
      `# Plan de implementación` via `caller.py:198-199`, `relevant` (`list[Module]`)
      still feeds `build_context()`.
- [ ] `--file` target is present in `relevant` in every run.
- [ ] `cache_read_input_tokens > 0` on a repeat `ctx task` (change 1 non-regression).
- [ ] The brief cites a real past ticket when one exists, and names covering tests or an
      explicit coverage gap.
- [ ] Any single specialist failing still yields a usable brief.
- [ ] The graph is compiled once per process, not per invocation.
- [ ] `dist\MAGNA.exe graph-selftest` exits 0 and `ctx task` runs end to end frozen.

## Proposal question round (automatic mode — needs user review)

1. **Latency budget**: `ctx task` gains two extra LLM calls. Is a slower but richer
   `ctx task` acceptable, or should Historiador/Vigía be opt-in (`--deep`)?
2. **Empty-signal behavior**: for a greenfield project with no ticket history and no
   tests, should the brief say so explicitly, or stay silent?
3. **Vigía's verdict weight**: should a coverage gap ever influence *which modules* are
   selected, or is it advisory text only? (Assumed: advisory only.)
4. **Size**: forecast is ~700 changed lines vs a 400 budget and `delivery_strategy:
   single-pr`. Split into two chained PRs (deps+packaging+Detective, then the other
   three nodes) or accept `size:exception`?
