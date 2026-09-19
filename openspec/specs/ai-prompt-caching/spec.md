# AI Prompt Caching Specification

## Purpose

Defines invariants for cacheable prompt prefixes on Anthropic Messages API
calls made by AICLI. Scoped to `_detect_relevant_modules`
(`aicli/commands/task.py:21-67`) only, per the approved proposal — the sole
call site with a stable, repeatable block large enough to benefit from
`cache_control`. This is a NEW capability: no prior spec exists for this
domain, and no other capability (`jira-resume-context`,
`ticket-history-store`) is modified.

## Requirements

### Requirement: Cacheable System Prefix

The Detective de Módulos node (`task_graph.py`, invoked by `run_task_graph`)
MUST place its content — the module listing (name, description, file path,
first-300-chars doc snippet per `Module`, narrowed to a task-relevant top-N
subset when the `ai-module-prefilter` semantic prefilter is active) and the
full `PROYECTO.md` text — in a leading `SystemMessage(content=[{...,
"cache_control":{"type":"ephemeral"}}])` passed as the first input message to
`create_agent`'s `.invoke()` call, so it is lifted into the request's
`system` array as a single text block carrying `cache_control: {"type":
"ephemeral"}`. The Detective MUST place all variable content (task
description, optional file hint, and the tool-use instruction) in a
subsequent `HumanMessage`, positioned so it never precedes the cached system
content. If the `SystemMessage` block does not survive `create_agent`'s
message handling, `AnthropicPromptCachingMiddleware` MAY be used as a
fallback transport, provided the exact block boundary is preserved. Unlike
`PROYECTO.md`, the module-listing portion of this cached block is no longer
guaranteed identical across calls with different `task_desc` values on large
projects, because the prefilter selects the listing's contents based on
`task_desc`; this is a deliberate, accepted tradeoff.
(Previously: built via a raw `system=` parameter on a single
`client.messages.create()` call inside `_detect_relevant_modules`, rather
than a leading `SystemMessage` fed into `create_agent`.)
(Reason: `_detect_relevant_modules` is deleted; the byte-identical cached
prefix and its content rules are unchanged — only the transport moves from a
raw `system=` string to a `SystemMessage` consumed by the ReAct loop, per
`ai-task-multiagent`.)

#### Scenario: Repeated call on an unchanged project shares an identical prefix

- GIVEN a project whose modules and `PROYECTO.md` have not changed since the last `ctx task` run, and the same `task_desc` is used
- WHEN the Detective node is invoked twice within the cache TTL
- THEN both invocations' leading `SystemMessage` content is byte-for-byte identical
- AND the second invocation's final `AIMessage.usage_metadata["input_token_details"]["cache_read"]` is greater than zero

#### Scenario: Task description may vary the cached module-listing portion; PROYECTO.md portion never varies

- GIVEN two Detective invocations with different `task_desc` values but the same modules and `PROYECTO.md`
- WHEN both invocations build their `SystemMessage`
- THEN the module-listing portion MAY differ, reflecting the task-relevant top-20 subset selected for each `task_desc`
- AND the `PROYECTO.md` portion MUST remain byte-for-byte identical between the two invocations

#### Scenario: Empty candidate list never reaches this node

- GIVEN `run_task_graph` has resolved zero candidate modules for the current project
- WHEN `_execute_task`'s module-count check runs
- THEN it returns early with a warning
- AND the Detective node is never invoked with an empty candidate list

### Requirement: Deterministic Module Listing Order

The module query backing the listing (`task.py:134`) MUST apply an explicit,
stable sort order (`ORDER BY Module.id`) instead of relying on unspecified
database row order. `Module.id` is chosen over `Module.name` because it is
the indexed primary key (free to sort on) and is verified stable across
re-indexing: `init.py`, `file_cmd.py`, and `sync.py` all upsert by
`(project_id, file_path)` — an existing row's fields are updated in place
(`existing.description = ...; session.add(existing)`) and only a genuinely
new `file_path` gets a new `Module(...)` row (see DEC-027, "upsert por
(project_id, file_path)"). No code path in this repository deletes and
recreates `Module` rows (verified: no `session.delete`/`DELETE FROM` on the
`Module` table exists anywhere), so `Module.id` never gets reassigned to an
already-documented module. Sorting by `Module.name` would instead reorder
the listing whenever a module is renamed, which is the actual cache-breaking
risk this requirement exists to prevent.

#### Scenario: Identical module set produces identical listing text

- GIVEN a project's module set is unchanged between two `ctx task` invocations
- WHEN the module query runs for each invocation
- THEN the resulting `listing` string is byte-for-byte identical both times, regardless of prior write/update order

### Requirement: Output Format and Behavior Preservation

Relocating module selection into the Detective node's `create_agent` ReAct
loop MUST NOT change its observable contract: it MUST still return only
module names present in the input `candidates` list, MUST still construct
its underlying model via `ChatAnthropic(model="claude-sonnet-5",
max_tokens=4000)` — WITHOUT `thinking` — and MUST NOT alter the
wording of the module-selection instructions in a way that changes selection
accuracy.
(Reason for omitting `thinking`: `ToolStrategy` forces `tool_choice="any"`
on every turn, and `langchain_anthropic` silently drops a forced
`tool_choice` whenever `thinking` is enabled, emitting an unsuppressed
runtime warning and leaving loop termination unguaranteed — see
`ai-structured-output`'s "Caching and Thinking Configuration Preserved"
requirement for the full mechanism.) The loop MUST expose iterative lookup tools (`leer_doc_modulo`,
`buscar_en_codigo`) without forcing `tool_choice`, and MUST end via a single
terminal structured response (`response_format=ToolStrategy(SeleccionarModulos)`)
rather than a `tool_choice`-forced call on every turn. Extraction MUST read
`result["structured_response"]` directly as an already-validated object
(with a documented fallback scan of `result["messages"]` for a terminal
`seleccionar_modulos` tool call) and MUST NOT call `json.loads` or
`json.JSONDecoder().raw_decode` on the response.
(Previously: required a single `client.messages.create()` call sending
`tools=[...]` with `tool_choice` forced to that tool's name on every call,
extraction reading the forced `ToolUseBlock.input` directly.)
(Reason: `_detect_relevant_modules`'s single-shot forced-`tool_choice` call
is deleted along with the function; the Detective's multi-turn loop cannot
force the same tool every turn without preventing genuine iteration, per
`ai-task-multiagent`/`ai-structured-output`. The structural-output guarantee
for the final answer is preserved via a terminal structured response.)

#### Scenario: Structured output succeeds unchanged

- GIVEN the Detective's ReAct loop runs for a real task
- WHEN it calls its terminal tool
- THEN `result["structured_response"]` contains the module-name array directly, requiring no JSON parsing
- AND the returned list contains only modules present in the input `candidates` list

#### Scenario: Cached system prefix is unaffected; thinking stays off

- GIVEN the loop uses iterative unforced tools plus one terminal structured response
- WHEN the underlying model is constructed and the request is built
- THEN the leading `SystemMessage` still carries the cached module-listing/`PROYECTO.md` block with `cache_control: {"type": "ephemeral"}` unchanged
- AND `thinking` is NOT set (omitted entirely, so `ToolStrategy`'s forced `tool_choice` is never silently dropped)
- AND `model` is still `"claude-sonnet-5"`

### Requirement: Cache Effectiveness Observability

Each call MUST make `response.usage.cache_creation_input_tokens` and
`response.usage.cache_read_input_tokens` (fields present in installed SDK
`anthropic==0.107.0`; exact field names to be confirmed against that SDK's
`Usage` model before implementation) visible via logging, so cache hit/miss
behavior is diagnosable without instrumenting a separate test harness.

#### Scenario: Cache write is logged on first call

- GIVEN the first `ctx task` run of a session for a given project
- WHEN `_detect_relevant_modules` completes its API call
- THEN a log record includes a non-zero `cache_creation_input_tokens` value

#### Scenario: Cache read is logged on a repeat call

- GIVEN a second `ctx task` run on the same project within the cache TTL
- WHEN `_detect_relevant_modules` completes its API call
- THEN a log record includes a non-zero `cache_read_input_tokens` value

### Requirement: Graceful Degradation Below Cache Threshold

WHEN the cached `system` block's token count falls below Anthropic's
minimum cacheable prefix length for `claude-sonnet-5`, the system MUST
continue to function exactly as if caching were not requested: `cache_control`
MUST be silently ignored by the API (no error raised), and module detection
MUST proceed and return correct results.

#### Scenario: Small project degrades to uncached behavior

- GIVEN a project whose module listing plus `PROYECTO.md` is smaller than the minimum cacheable prefix
- WHEN `_detect_relevant_modules` sends the request with `cache_control` set
- THEN the API call succeeds without error
- AND `response.usage.cache_creation_input_tokens` and `cache_read_input_tokens` are both zero
- AND module selection results are unaffected
