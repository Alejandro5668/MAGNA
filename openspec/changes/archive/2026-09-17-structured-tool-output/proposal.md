# Proposal: Structured tool output — replace prose-JSON + hand-rolled repair

## Intent

Four Claude calls ask for JSON inside prose and parse it by hand. `_reparar_json` (`indexer.py:132-152`) exists because that failure is **real, not hypothetical** (`TODO.md:179`). Today: `ctx init` crashes on a malformed response (`init.py:195` is unwrapped); `ctx task` parses with bare `raw_decode` and no safety net; `ctx sync` silently degrades case memory to empty strings. Forced `tool_choice` makes non-conforming output structurally impossible, so the repair helper becomes dead code instead of a load-bearing one.

## Scope

### In Scope
- All 4 sites migrate to `tools` + `tool_choice={"type":"tool","name":...}`; `ToolUseBlock.input` is already a dict — no `json.loads` anywhere.
- One shared schema for `document_architecture` + `document_zone` (identical 6-key shape, array wrapped in an object per `ToolParam` constraint); one 5-key schema for `generate_case_summary`; one string-array schema for `_detect_relevant_modules`.
- Delete `_parse_json_claude` + `_reparar_json` — **only valid because all 3 of their callers migrate here**. Dropping any one site keeps both helpers alive and forfeits the headline outcome.
- Delete inline `Devolvé ÚNICAMENTE este JSON: {...}` prompt blocks the schema now replaces.

### Out of Scope
| Item | Why |
|---|---|
| `generate_module_content`, `analyze_file_deep`, `generate_project_md`, `generate_role_md` | Pure markdown — no JSON to structure (confirmed in exploration) |
| `describe_image` | Free-text vision output |
| `tickets.py` / `init.py:78` `json.loads` | Local cache files, not model output |
| `sync.py:291` unbound-`jira_msg` bug | Pre-existing; unchanged reachability. Follow-up |
| Retry/backoff and 4x `Anthropic()` consolidation | Inherited deferral from change 1 |

## Capabilities

### New Capabilities
- `ai-structured-output`: invariants for schema-forced tool calls — forced `tool_choice`, object-typed top-level schema, tool-input extraction, no manual JSON parsing.

### Modified Capabilities
- `ai-prompt-caching`: its "Output Format and Behavior Preservation" requirement pins `_detect_relevant_modules` to "a JSON array of module name strings parseable by the strict parse at `task.py:64-66`". That parse is being removed. Delta must re-pin the requirement to tool-input extraction while preserving `claude-sonnet-5`, `thinking:{"type":"adaptive"}`, and the cached `system` prefix.

## Approach

Primary: `tools` + forced `tool_choice`. Verified compatible with adaptive thinking (manual `thinking:"enabled"` would block it) and non-regressive for change 1 — `tool_choice` invalidates cached *message* blocks, not cached `system`/tool-definition blocks, and the prefix is static.

Documented escape hatch, per site: `output_config={"format":{"type":"json_schema",...}}`. Real and installed, but at plain `.create()` it still returns a text block needing manual `json.loads` — removes malformed-JSON risk, not the parse line. Not the default.

`_call_claude` serves 6 operations, 3 staying pure-markdown. Design must add structured support without forcing schemas on markdown callers — likely a sibling helper sharing the retry loop, not a widened signature.

## Decision: `generate_case_summary` fallback

**Remove it as dead code.** Verified: `_call_claude` runs at `indexer.py:287`, *outside* the `try:` at 288 — so the `except` at 297-299 catches **only** parse/validation errors, never network, rate-limit, or auth failures. Those already propagate and are already handled by the caller (`sync.py:284-289`, user-facing warning). Once forced tool use removes the parse, the branch is provably unreachable.

- Non-conforming output: impossible by construction; `required_keys` becomes redundant with schema `required`.
- API failure: **unchanged** — propagates to `sync.py`, same warning as today.
- Net: silent-empty-memory degradation disappears; no new crash surface.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `aicli/commands/task.py:21-82` | Modified | Tool + forced choice; drop `raw_decode`; keep cached `system` and adaptive thinking |
| `aicli/services/indexer.py:132-152,166-178` | Removed | `_reparar_json`, `_parse_json_claude` |
| `aicli/services/indexer.py:181-219` | Modified | Structured-call path alongside `_call_claude` |
| `aicli/services/indexer.py:248-299` | Modified | 5-key schema; dead fallback removed |
| `aicli/services/indexer.py:437-518,706-818` | Modified | Shared module-list schema |
| `tests/` | New | Offline payload-shape + tool-input-extraction tests |

## Review budget — flagged, not assumed

Cached strategy is `single-pr` at 400 lines. This does **not** comfortably fit. Forecast: helper ~50, schemas ~35, four call-site edits ~90 (prompt-block deletions count), helper deletion ~35, tests ~180 → **≈390, zero margin** — and change 1 touched one site where this touches four.

Pre-authorized seam if `sdd-tasks` forecasts overrun, split by file and mechanism:
- **Slice A** — `task.py` `_detect_relevant_modules` only (own `messages.create`, no shared helper, no dependency on B).
- **Slice B** — `indexer.py`: structured helper, both schemas, 3 call sites, helper deletion.

Both stand alone and roll back independently; the `_parse_json_claude` deletion lives entirely in B. Changing delivery strategy is the user's call, not this phase's.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| 400-line budget exceeded | **High** | Pre-authorized A/B seam above; `sdd-tasks` forecasts before apply |
| Widening `_call_claude` pollutes 3 markdown callers | Med | Design must choose a sibling helper or keyword-optional path; no schema on markdown calls |
| `document_zone`/`document_architecture` schemas diverge | Med | One shared constant, mandated in scope, not left to apply |
| Caching regression on the hot path | Low | Static tool definitions only; verify `cache_read_input_tokens > 0` still holds in `sdd-verify` |
| Forced tool use shifts selection quality on `ctx task` | Med | Keep instruction wording; compare selections on a real task before/after |
| Schema over-constrains (`domain: null`, `category` enum) and the model truncates | Med | Nullable `domain`, enum only where values are closed; design states each field's nullability |

## Rollback Plan

**Revert the diff — complete, verified.** No schema change, no migration, no new dependency (`tools`/`tool_choice` are native to pinned `anthropic==0.107.0`), no config key, no on-disk artifact, no persisted format change: `document_*` still returns `list[dict]`, `generate_case_summary` still returns `(str, dict, int)`. Modules written to SQLite before and after are shape-identical. Nothing to clean up.

## Dependencies

- Change 1 `prompt-caching` (shipped) — this builds on the `system`-array shape in `task.py`; must not undo it.
- Blocks change 4 `module-semantic-prefilter`.

## Success Criteria

- [ ] All 4 sites call with `tools` + forced `tool_choice`; zero `json.loads`/`raw_decode` on model output remains.
- [ ] `_parse_json_claude` and `_reparar_json` are gone and no reference survives.
- [ ] `ctx init`, `ctx file <zona>`, `ctx task`, `ctx sync` each complete a real run with unchanged output shape.
- [ ] Second `ctx task` within TTL still logs `cache_read_input_tokens > 0` (change 1 not regressed).
- [ ] `ai-prompt-caching` delta lands with the change — the two specs never contradict each other.
- [ ] Line count fits 400, or the A/B split is accepted by the user before apply.

## Proposal question round (deferred — automatic execution mode)

Not asked; assumptions made. Flag for user review:
1. **Is removing `generate_case_summary`'s fallback acceptable?** Assumed yes — it only ever caught parse errors, and the caller already warns on API failure. If the user wants a belt-and-braces degraded path anyway, say so before `sdd-design`.
2. **`single-pr` vs the A/B split?** Assumed single-pr until `sdd-tasks` proves otherwise. If the user prefers two reviewable slices up front, decide now — the seam is cheaper before apply than after.
3. **Should `ctx task` module-selection quality be measured, or is "it parses" enough?** Assumed a spot-check against one real task, not a benchmark.
4. **`category` as a closed enum?** Assumed yes (backend/frontend/infraestructura/negocio, already stated in both prompts). If new categories are expected, the schema must stay open or this silently blocks them.
