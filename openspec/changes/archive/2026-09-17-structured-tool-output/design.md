# Design: Structured tool output

## Technical Approach

Four call sites stop asking for JSON in prose and start declaring a tool with an
`input_schema`, forced via `tool_choice={"type":"tool","name":...}`. Per-key
instruction text moves *verbatim* from the inline `Devolvé ÚNICAMENTE este JSON`
blocks into JSON-Schema `description` fields — no wording is lost, so selection
and documentation quality are not silently changed. `ToolUseBlock.input` is
already a `dict`, so `_parse_json_claude` / `_reparar_json` lose all callers and
are deleted. Implements `specs/ai-structured-output/spec.md`; preserves
`ai-prompt-caching`'s `system`-array/`cache_control` shape untouched.

## Architecture Decisions

### Decision: one shared extractor, not four inline loops

**Choice**: add `_extract_tool_input(content_blocks, tool_name) -> dict` in
`indexer.py`, mirroring the existing `_extract_text` (same shape, same
`RuntimeError`, Spanish message). `task.py` imports it — it already imports
`_extract_text` from `indexer.py` (`task.py:14`).
**Rejected**: inline `next(b for b in response.content if b.type=="tool_use")`
per site (4x duplication, 4 divergent error messages).
**Rationale**: matches the file's established pattern; one place to change.

```python
def _extract_tool_input(content_blocks, tool_name: str) -> dict:
    """Input ya parseado del ToolUseBlock forzado — sin json.loads."""
    for block in content_blocks:
        if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
            return block.input
    raise RuntimeError(f"Respuesta de Claude sin bloque tool_use para '{tool_name}'")
```

### Decision: extract the retry loop; do NOT widen `_call_claude`

`_call_claude` serves 6 operations; only 3 migrate.

| Option | Tradeoff | Verdict |
|---|---|---|
| Optional `tools=`/`tool_choice=` kwargs on `_call_claude` | Return type becomes `tuple[str\|dict,int]` discriminated by a kwarg; widens the contract of 3 markdown callers | Rejected |
| Parallel `_call_claude_tool` duplicating the 28-line backoff loop | ~51 fewer diff lines, but creates real duplication in the only API path | Rejected |
| **Extract `_messages_create_retry(**kwargs) -> Message`; `_call_claude` and `_call_claude_tool` become thin wrappers** | Higher churn on a shared path, offset by one retry/log implementation | **Chosen** |

**Rationale**: CLAUDE.md says abstract on *real* duplication and "no abstractions
before two concrete implementations" — there are now exactly two (text call, tool
call). `_call_claude` keeps its exact signature, model resolution, log format and
`tuple[str,int]` return, so `generate_module_content`, `analyze_file_deep` and
`generate_project_md` are byte-unaffected (guarded by a test).

```python
def _call_claude_tool(prompt: str, tool: dict, context: str = "",
                      max_tokens: int = 8192, model: str | None = None) -> tuple[dict, int]:
    response = _messages_create_retry(
        context, len(prompt) // 4,
        model=model or MODEL_BY_OPERATION["architecture"], max_tokens=max_tokens,
        tools=[tool], tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": prompt}],
    )
    usage = response.usage
    return _extract_tool_input(response.content, tool["name"]), usage.input_tokens + usage.output_tokens
```

### Decision: ONE shared schema for `document_architecture` + `document_zone`

**Verified by reading both prompts** (`indexer.py:499-510` and `796-808`): the key
sets are *identical* — `name`, `description`, `file_path`, `category`, `domain`,
`documentation`. Only the `file_path` example (`{zone}/ArchivoReal.php` vs
`modulo/ArchivoMain.php`) and the cap (8 vs 15) differ, and both are
instruction-level — they stay in the prompt, not the schema.
**Choice**: one `MODULE_ITEM_SCHEMA` + one `DOCUMENT_MODULES_TOOL` constant, used
by both. **Rejected**: two near-identical constants (guaranteed drift; the
proposal lists divergence as a Med risk).

```python
MODULE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "nombre_snake_case"},
        "description": {"type": "string", "description": "Qué hace, en una línea, basado en el código real."},
        "file_path": {"type": "string", "description": "Ruta relativa al proyecto con extensión real. Nunca una carpeta."},
        "category": {"type": "string", "enum": ["backend", "frontend", "infraestructura", "negocio"]},
        "domain": {"type": ["string", "null"], "description": "Dominio de negocio, o null."},
        "documentation": {"type": "string", "description": "Markdown, secciones cortas, \\n para saltos, sin backticks."},
    },
    "required": ["name", "description", "file_path", "category", "domain", "documentation"],
    "additionalProperties": False,
}
DOCUMENT_MODULES_TOOL = {
    "name": "documentar_modulos",
    "description": "Registra los módulos/componentes documentados.",
    "input_schema": {"type": "object",
                     "properties": {"modules": {"type": "array", "items": MODULE_ITEM_SCHEMA}},
                     "required": ["modules"]},
}
```

`domain` is **nullable-but-required**: both prompts already show `"domain": null`,
so a non-nullable field would force invention; `required` forces an explicit
`null` and preserves today's `m.get("domain")` behavior at `init.py:148`.
`category` is a **closed enum** — both prompts already state exactly those four
values. Escape hatch if a fifth appears: delete the `enum` key.

Call-site shape (identical in both functions, only `context`/`max_tokens`/`model`
differ), replacing `_call_claude(...)` + `_parse_json_claude(text)`:

```python
data, tokens = _call_claude_tool(prompt, DOCUMENT_MODULES_TOOL,
                                 context=f"zona:{zone_display}", max_tokens=8192,
                                 model=MODEL_BY_OPERATION["zone"])
modules = data["modules"]          # list[dict] — return shape unchanged
```

### Decision: `generate_case_summary` — schema + no try/except

Already object-shaped; no array wrapping. The five long instruction strings inside
today's JSON literal (`indexer.py:280-284`) become the five `description` values
verbatim, and the whole `Genera un JSON...{...}` block leaves the prompt.

```python
CASE_SUMMARY_TOOL = {
    "name": "registrar_resumen_caso",
    "description": "Registra el mensaje de Jira y la memoria estructurada del caso.",
    "input_schema": {"type": "object", "properties": {
        "jira": {"type": "string", "description": "<texto actual de indexer.py:280, verbatim>"},
        "pasos_qa": {"type": "string", "description": "<indexer.py:281, verbatim>"},
        "investigado": {"type": "string", "description": "<indexer.py:282, verbatim>"},
        "hecho": {"type": "string", "description": "<indexer.py:283, verbatim>"},
        "tener_en_cuenta": {"type": "string", "description": "<indexer.py:284, verbatim>"},
    }, "required": ["jira", "pasos_qa", "investigado", "hecho", "tener_en_cuenta"],
       "additionalProperties": False},
}
```

Body after (replaces lines 287-299 — `required_keys` is now redundant with schema
`required`, and the `except` at 297-299 was verified dead: `_call_claude` ran
*outside* the `try`, so API failures already propagate to `sync.py:284-289`):

```python
    data, tokens = _call_claude_tool(prompt, CASE_SUMMARY_TOOL, context="resumen-caso",
                                     max_tokens=1000, model=MODEL_BY_OPERATION["case_summary"])
    case_memory = {k: data[k] for k in ("investigado", "hecho", "tener_en_cuenta", "pasos_qa")}
    return data["jira"], case_memory, tokens
```

Direct indexing, not `.get` — `required` guarantees the keys, and a `KeyError`
is the loud failure the spec's "pathological failures propagate" requirement wants.
Return contract `tuple[str, dict, int]` unchanged.

### Decision: `_detect_relevant_modules` keeps its own inline client

It already bypasses `_call_claude` (change 1). Keep it that way — consolidating the
4 `Anthropic()` instantiations is an explicitly deferred out-of-scope item.

```python
MODULE_SELECTION_TOOL = {
    "name": "seleccionar_modulos",
    "description": "Devuelve los módulos relevantes para la tarea.",
    "input_schema": {"type": "object", "properties": {
        "modules": {"type": "array", "items": {"type": "string"},
                    "description": "Nombres exactos de los módulos relevantes, tal como aparecen en el listado."}},
        "required": ["modules"]},
}
```

Before / after at `task.py:52-82`:

```diff
-Analizá la tarea, entendé qué partes del sistema necesita tocar, y devolvé ÚNICAMENTE
-un JSON con los nombres de los módulos relevantes, sin texto adicional:
-["nombre_modulo_1", "nombre_modulo_2"]
+Analizá la tarea, entendé qué partes del sistema necesita tocar y llamá a la
+herramienta seleccionar_modulos con los nombres de los módulos relevantes.

 Seleccioná solo los módulos que realmente necesitarán ser leídos o modificados.
 Si no podés filtrar con seguridad, devolvé todos los nombres."""

     response = client.messages.create(
         model="claude-sonnet-5",
         max_tokens=4000,
         thinking={"type": "adaptive"},
         system=system_blocks,
+        tools=[MODULE_SELECTION_TOOL],
+        tool_choice={"type": "tool", "name": MODULE_SELECTION_TOOL["name"]},
         messages=[{"role": "user", "content": user_prompt}]
     )
     ... usage logging unchanged ...
-    text = next(b.text for b in response.content if b.type == "text")
-    text = text.strip().removeprefix("```json")...
-    names, _ = json.JSONDecoder().raw_decode(text)
+    names = _extract_tool_input(response.content, MODULE_SELECTION_TOOL["name"])["modules"]
     return [m for m in modules if m.name in names]
```

`system_blocks`, `cache_control`, `model`, `max_tokens`, `thinking` and the usage
logging are **untouched** — change 1 is preserved literally.

**Caching note for `sdd-verify`**: `tools` sits *before* `system` in the cache
prefix, so adding a `tools` array changes the prefix bytes **once**. The first
post-deploy `ctx task` is a cache *write*, not a read; from the second call on,
`cache_read_input_tokens > 0` must hold again. Verification must compare two calls
*after* deploy, not across the deploy boundary.

## Data Flow

    prompt ──→ _call_claude_tool ──→ _messages_create_retry ──→ Messages API
                                              │                      │
                       _call_claude (text) ───┘              ToolUseBlock.input
                       (3 markdown callers, unchanged)               │
                                                      _extract_tool_input ──→ dict
                                                                     │
                                       list[dict] / (jira, memoria, tokens) / list[Module]

## File Changes

| File | Action | Description |
|---|---|---|
| `aicli/services/indexer.py` | Modify | `+_extract_tool_input`, `+_messages_create_retry`, `+_call_claude_tool`, 3 schema constants, 3 call sites |
| `aicli/services/indexer.py` | Delete | `_reparar_json` (132-152), `_parse_json_claude` (166-178), `import json` (line 6 — no other `json.` use remains in this file, verified) |
| `aicli/commands/task.py` | Modify | `MODULE_SELECTION_TOOL`, tools/tool_choice on `messages.create`, `_extract_tool_input` import; `import json` **stays** (lines 312/318 read the receipt file) |
| `tests/test_prompt_caching.py` | Modify | `_stub_response` must emit a `tool_use` block; `test_json_parse_and_filter_by_name` rewritten |
| `tests/test_structured_output.py` | Create | Payload-shape + extraction tests for all 4 sites |

## Deletion safety

Every current caller, verified by grep:

| Caller | Line | Migrates? |
|---|---|---|
| `generate_case_summary` | `indexer.py:289` | Yes |
| `document_zone` | `indexer.py:513` | Yes |
| `document_architecture` | `indexer.py:812` | Yes |
| `_reparar_json` ← `_parse_json_claude` | `indexer.py:173` | Deleted with its only caller |

No other reference exists outside `openspec/` and `TODO.md:179` (historical log —
leave it). `_extract_text` stays: still used by `_call_claude`, `describe_image`,
and `task.py:120`.

## Testing Strategy

Established style (`tests/test_prompt_caching.py`): `@patch("anthropic.Anthropic")`,
inspect `mock_create.call_args.kwargs`, zero network.

```python
def _tool_response(tool_name, payload, cache_read=0):
    usage = MagicMock(input_tokens=500, output_tokens=20,
                      cache_creation_input_tokens=100, cache_read_input_tokens=cache_read)
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking"),
                 SimpleNamespace(type="tool_use", name=tool_name, input=payload)],
        usage=usage)
```

The leading non-`tool_use` block is deliberate — it proves the extractor skips
`ThinkingBlock` (the exact bug fixed in commit `ba41364` for `_extract_text`).

| Layer | What | Assertion |
|---|---|---|
| Unit | 4 sites send `tools` + forced `tool_choice` | `kwargs["tools"][0]["input_schema"]["type"] == "object"`; `kwargs["tool_choice"] == {"type":"tool","name":<n>}` |
| Unit | No manual parsing | `inspect.getsource` of each site contains no `json.loads` / `raw_decode` |
| Unit | Shared schema | `document_zone` and `document_architecture` send the *same* `tools` object |
| Unit | Unwrapping | `input={"modules":[...]}` → return value is the bare `list[dict]` |
| Unit | `generate_case_summary` | returns `(jira, 4-key memoria, tokens)`; missing key raises, no empty-string fallback |
| Unit | Change-1 non-regression | `system`/`cache_control`/`thinking`/`model` identical to pre-change assertions |
| Unit | Markdown callers unaffected | `_call_claude` signature + `tuple[str,int]` return unchanged; its kwargs contain **no** `tools` key |
| Unit | Extractor | skips thinking/text blocks; raises `RuntimeError` when the tool block is absent |
| Manual | Real run | `ctx init`, `ctx file <zona>`, `ctx task`, `ctx sync` — unchanged output shape |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file
classification, or process-integration boundary. `caller.py`'s subprocess launch
is untouched; this change only alters request payload shape and response reading.

## Review Workload Forecast (input to `sdd-tasks`)

| Unit | Changed lines (add+del) |
|---|---|
| A — `task.py` site + tool constant + extractor + test updates | **≈125** |
| B — retry extraction + `_call_claude_tool` | ≈96 |
| B — 3 schema constants | ≈60 |
| B — 3 call sites (incl. prompt-block deletions) | ≈95 |
| B — helper deletions | ≈35 |
| B — tests | ≈140 |
| **B total** | **≈426** |
| **Single PR** | **≈551** |

*(Corrected by orchestrator gate: the original draft summed these five B line
items to ≈366 and Single PR to ≈491 — arithmetic error, off by exactly the
"3 schema constants" line. 125+96+60+95+35+140 = 551, not 491. This makes the
case for the split stronger, not weaker — the true overage is larger than
first stated.)*

**Recommendation: use the pre-authorized A/B split.** The proposal's ≈390 estimate
predates the retry-extraction decision (+~50) and the `test_prompt_caching.py`
stub migration (+~25), which only surfaced once the diffs were written. ≈551
does not fit 400; A (≈125) fits on its own, B (≈426) does not and should use
the B1/B2 seam below if taken as its own PR.

**Ordering constraint — a correction to the proposal**: the slices are *not* fully
independent. `_extract_tool_input` is shared, so it lands in **A** (inside
`indexer.py`, next to `_extract_text`) and **A must merge before B**. B still
rolls back independently; A rolls back independently only if B has not landed.
If B itself overruns, the next seam is B1 (helper + deletions + `generate_case_summary`)
then B2 (shared schema + both `document_*`).

## Migration / Rollout

No migration. Pure code change: no DB schema change, no data backfill, no new
dependency (`tools`/`tool_choice` are native to pinned `anthropic==0.107.0`), no
config key, no on-disk format change. `document_*` still returns `list[dict]`,
`generate_case_summary` still returns `(str, dict, int)`. Rollback = revert.

## Open Questions

- [ ] `single-pr` vs the split — this design forecasts ≈551 lines (corrected,
      see Review Workload Forecast). A (≈125) fits a single PR; B (≈426) does
      not fit on its own either, so a strict 400-line budget means **three**
      PR units (A, B1, B2), not two. **User decision required before `sdd-apply`**:
      accept the 3-unit split, or invoke `size:exception` for B as one PR.
- [x] ~~`openspec/changes/structured-tool-output/specs/` currently contains only
      `ai-structured-output/`... Missing~~ — **false, struck by orchestrator gate.**
      Both `specs/ai-structured-output/spec.md` and `specs/ai-prompt-caching/spec.md`
      (the required MODIFIED delta) exist, are complete, and correctly re-pin the
      `_detect_relevant_modules` contract to `ToolUseBlock.input` extraction. This
      was a false claim in the original draft, not a stale-artifact timing issue —
      verified independently twice (orchestrator + fresh-context validator).
- [ ] `prompts/architecture_detect.md`, `prompts/zone_document.md`,
      `prompts/sync_case_summary.md` are documentation mirrors of the three
      migrated prompts (not read at runtime — verified: no code reads `prompts/`).
      They will drift. Recommend a follow-up doc sync rather than adding ~60 lines
      to an already-over-budget change.
- [ ] `category` as a closed enum blocks any future fifth category silently.
      Accepted per proposal question 4; escape hatch documented above.
