# Delta for AI Prompt Caching

## MODIFIED Requirements

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
