# Exploration: structured-tool-output — replace prose-JSON+repair with real Anthropic tool_use/input_schema

## Current State

**`aicli/services/indexer.py`**: `_reparar_json()` (132-152) is a deliberate safety net for literal newlines inside JSON string values — `TODO.md:179` confirms it was built specifically for this ("Incluye `_reparar_json()` como safety net para JSON con saltos de línea literales"), so it's a confirmed real failure mode, not speculative. `_parse_json_claude()` (166-178) does fence-strip → `json.loads` → repair-fallback → `required_keys` check. Three call sites use it:
- `generate_case_summary()` (248-299) — 5-key JSON object, has `required_keys` validation, and a real `try/except` fallback (289-299) that silently returns empty strings on parse failure (user-visible Jira-comment degradation).
- `document_zone()` (437-518) — JSON array of 6-key objects, no `required_keys`; caller `file_cmd.py:95-103` wraps it in try/except with a graceful error message.
- `document_architecture()` (706-818) — same shape as `document_zone`, but caller `init.py:195` has **no try/except** (verified: `document_architecture(...)` is called directly, unwrapped) — this runs during `ctx init`, so a parse failure crashes the tool's first-run entry point.
- `generate_module_content`, `analyze_file_deep`, `generate_project_md` confirmed pure-markdown output — out of scope.

**`aicli/commands/task.py`**: `_detect_relevant_modules()` (21-82), already restructured by change 1 (`prompt-caching`) into a `system`-array cached prefix + variable user-turn suffix, parses via `json.JSONDecoder().raw_decode(text)` (80-81) with **no** `_parse_json_claude`, no repair, no `required_keys`, no try/except — the most fragile site, and the hottest (every `ctx task` run). Uses `thinking={"type":"adaptive"}` (task.py:65).

`tickets.py`/`init.py:78` `json.loads` calls read local cache files, not Claude output — out of scope.

## Verified SDK Facts (`anthropic==0.107.0`, `.venv/Lib/site-packages/anthropic/`)

- `ToolParam.input_schema` requires `type: Required[Literal["object"]]` at the top level (`types/tool_param.py:15-30`) — **a bare JSON array cannot be a tool's top-level schema**, so 3 of 4 call sites need array-in-object wrapping.
- `ToolChoiceToolParam = {"type":"tool","name":str}` forces a specific tool (`types/tool_choice_tool_param.py`).
- `ToolUseBlock.input: Dict[str, object]` is already a parsed dict (`types/tool_use_block.py:19-29`) — zero manual `json.loads` needed.
- A second, independently real mechanism exists: `output_config={"format":{"type":"json_schema","schema":{...}}}` (`types/output_config_param.py`, `types/json_output_format_param.py`, wired at `messages.py:119,1019`). Verified via `lib/_parse/_response.py` that at the plain `.create()` level this still returns a `text` block requiring manual `json.loads()` — only `.stream()`/pydantic `.parse()` auto-populate `.parsed_output`. So it removes malformed-JSON risk but not the manual-parse line.

## Thinking + tool_choice (resolved, verified live via WebFetch — not assumed)

Anthropic's docs state manual extended thinking (`type:"enabled"`) blocks forced `tool_choice` (`any`/`tool` error out), but **adaptive thinking explicitly supports forced tool use**. `_detect_relevant_modules` uses `thinking={"type":"adaptive"}`, so this is not a blocker. Also confirmed: changing `tool_choice` invalidates cached *message* blocks but not cached `system`/tool-definition blocks, so a static `tools`/`tool_choice` addition does not regress change 1's caching win.

## Recommendation

Primary mechanism: `tools` + forced `tool_choice` (matches the change's stated intent — zero manual JSON handling). Recommended `sdd-propose` scope, ranked: (1) `_detect_relevant_modules` — hottest path, zero safety net; (2) `document_architecture` — uncaught crash on `ctx init`; (3) `generate_case_summary` — confirmed-plausible silent-degradation fallback; (4) `document_zone` — same shape as #2, lower urgency, consider sharing one schema with `document_architecture`. Flag `output_config.format` in the proposal as a real, verified, lower-effort alternative rather than silently discarding it — note it doesn't fully satisfy "no manual JSON parsing at all."

## Risks

- Array-to-object schema wrapping required for 3 of 4 sites (verified SDK constraint).
- Shared `_call_claude()` helper serves 6 operations; only 2-4 need `tools=`/`tool_choice=` — needs a design decision to avoid polluting pure-markdown callers.
- `document_zone`/`document_architecture` are near-duplicate prompts — risk of divergent schemas if not consolidated in design.
- `output_config.format` + adaptive thinking compatibility not found documented — flag for live verification in `sdd-design` if Approach 2 is ever chosen.
- `generate_case_summary`'s silent-empty fallback becoming a hard error is a behavior change belonging to `sdd-propose`'s scope discussion, not this exploration.

## Ready for Proposal

Yes — 4 call sites identified and ranked by fragility evidence, primary mechanism (tools/tool_choice) verified against the installed SDK, thinking-compatibility risk resolved.
