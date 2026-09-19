# AI Structured Output Specification

## Purpose

Defines invariants for schema-forced tool-call output on Anthropic Messages
API calls made by AICLI, replacing prose-JSON output parsed by hand. Covers
all 4 call sites migrated by this change: `_detect_relevant_modules`
(`task.py`), `document_architecture`, `document_zone`, and
`generate_case_summary` (`indexer.py`). This is a NEW capability — no prior
spec exists for this domain.

## Requirements

### Requirement: Forced Tool Choice for Structured Calls

Each single-shot call site among `document_architecture`, `document_zone`,
and `generate_case_summary` MUST send `tools=[...]` with exactly one tool
whose `input_schema` is a JSON Schema with top-level `type: "object"`, and
MUST set `tool_choice={"type": "tool", "name": <that tool's name>}` on
every API call, so the model cannot reply in free-form prose.

Detective de Módulos's multi-turn agent loop (replacing
`_detect_relevant_modules`, per `ai-task-multiagent`) is exempt from the
"forced on every call" semantic: it MUST expose its intermediate-lookup
tools (e.g. `leer_doc_modulo`, `buscar_en_codigo`) without a forced
`tool_choice`, and MUST expose exactly one designated terminal tool (e.g.
`seleccionar_modulos`) that the agent calls when it decides it is done.
This terminal call MUST still be a structured tool-use response —
`ToolUseBlock.input` extraction still applies, no `json.loads` is
reintroduced — but termination is enforced by the loop's exit condition
(invocation of the terminal tool), not by forcing that exact `tool_choice`
on every individual API call within the loop.
(Reason: `_detect_relevant_modules`'s prior single-shot forced-tool_choice
pattern cannot hold inside a multi-turn loop — forcing the same
`tool_choice` every turn would force the agent to immediately call the
final-answer tool and never take an intermediate lookup turn. Replacing it
with unforced intermediate tools plus one loop-terminal tool preserves the
"no free-form prose in structured output" guarantee for the final answer
while allowing genuine iteration.)
(Previously: applied identically to all 4 migrated call sites, including
`_detect_relevant_modules`, with `tool_choice` forced on every single API
call for each.)

#### Scenario: Model output is structurally forced for single-shot call sites

- GIVEN any of `document_architecture`, `document_zone`, or
  `generate_case_summary` builds a request
- WHEN the request is sent to the Messages API
- THEN the request includes `tools` with one tool definition and
  `tool_choice` naming that exact tool
- AND the API response's content contains a `tool_use` block for that tool

#### Scenario: Detective's loop calls a terminal tool without forcing it every turn

- GIVEN Detective de Módulos's agent loop is running
- WHEN it decides it has enough information to answer
- THEN it calls the designated terminal tool (`seleccionar_modulos`)
- AND the loop ends upon that call
- AND no earlier turn in the loop had `tool_choice` forced to that
  terminal tool

#### Scenario: Terminal tool output is still consumed without manual parsing

- GIVEN Detective de Módulos's loop has called its terminal tool
- WHEN the call site extracts the result
- THEN it reads the terminal tool's `ToolUseBlock.input` directly as a
  dict
- AND no `json.loads`/`raw_decode` call executes anywhere in that code
  path

### Requirement: No Manual JSON Parsing of Tool Output

Response parsing at the 4 migrated call sites MUST read the matching
`ToolUseBlock.input` directly, since it is already a parsed `dict`. These
call sites MUST NOT call `json.loads`, `json.JSONDecoder().raw_decode`, or
any other manual JSON-parsing mechanism on model output.

#### Scenario: Tool input is consumed without parsing

- GIVEN a response contains a `tool_use` block for the forced tool
- WHEN the call site extracts its result
- THEN it reads `block.input` directly as a dict
- AND no `json.loads`/`raw_decode` call executes anywhere in that code path

### Requirement: Array-Shaped Output Wrapped in an Object

Call sites whose logical output is an array (`document_architecture`,
`document_zone`) MUST wrap that array in an object field (e.g.
`{"modules": [...]}`) in their `input_schema`, because a bare JSON array
cannot be a tool's top-level `input_schema` (SDK constraint:
`ToolParam.input_schema` requires top-level `type: "object"`).

#### Scenario: Module-list output is unwrapped after extraction

- GIVEN `document_architecture` or `document_zone` receives a `tool_use`
  block whose `input` is `{"modules": [...]}`
- WHEN the call site builds its return value
- THEN it returns the unwrapped `list[dict]` extracted from the `modules`
  key, preserving the pre-migration return shape

### Requirement: Caching and Thinking Configuration Preserved

Relocating module selection into Detective de Módulos's `create_agent`
ReAct loop (replacing `_detect_relevant_modules`, per `ai-task-multiagent`)
MUST preserve the cached `system`-array/`cache_control` structure and the
`claude-sonnet-5` model id. The Detective's underlying model MUST be
constructed as `ChatAnthropic(model="claude-sonnet-5", max_tokens=4000)`,
WITHOUT `thinking`. `thinking` MUST NOT be enabled on the Detective's model.
(Previously: named `_detect_relevant_modules`'s `client.messages.create()`
call directly, prior to its deletion.)
(Reason: `_detect_relevant_modules` no longer exists; this requirement's
subject moves to the Detective's `ChatAnthropic` instance, which replaces
the deleted function's single call while keeping the same model id and
cache configuration. `thinking` is dropped from the Detective specifically
because `ToolStrategy`'s forced `tool_choice="any"` is silently discarded by
`langchain_anthropic` whenever `thinking` is enabled — a documented Anthropic
API incompatibility between forced tool choice and extended thinking — which
would have made the Detective's loop-termination guarantee unreliable.)

#### Scenario: Cached prefix survives relocation to the Detective node without enabling thinking

- GIVEN Detective de Módulos is constructed via `ChatAnthropic(model="claude-sonnet-5", max_tokens=4000)`
- WHEN a request is built for the ReAct loop
- THEN no `thinking` parameter is present on the model
- AND the leading `SystemMessage` still carries the cached module-listing/`PROYECTO.md` block with `cache_control: {"type": "ephemeral"}` unchanged

### Requirement: Dead JSON-Repair Code Removed

`_parse_json_claude` and `_reparar_json` (`indexer.py`) MUST be deleted once
all 3 of their callers (`generate_case_summary`, `document_zone`,
`document_architecture`) have migrated to forced tool output. Neither
helper MUST remain if any caller is left unmigrated.

#### Scenario: Repair helpers have no remaining callers

- GIVEN all 4 call sites use `tools`/`tool_choice`
- WHEN the codebase is searched for `_parse_json_claude` or `_reparar_json`
- THEN no definition or call site remains

### Requirement: Structural Guarantee Removes Parse-Failure Fallback

`generate_case_summary`'s fallback that returned empty-string case memory on
parse failure MUST be removed as dead code, because forced `tool_choice`
makes non-conforming tool input structurally impossible. This removal MUST
NOT change API-failure handling: `_call_claude` failures (network, rate
limit, auth) MUST continue to propagate unchanged to `sync.py`'s existing
caller-side warning.

#### Scenario: Malformed output no longer degrades silently

- GIVEN `generate_case_summary` is migrated to forced tool output
- WHEN the codebase is inspected for a parse-failure fallback returning
  empty strings
- THEN no such fallback exists

#### Scenario: API failures still propagate to the existing caller warning

- GIVEN `_call_claude` raises due to a network, rate-limit, or auth failure
  during `generate_case_summary`
- WHEN the exception is raised
- THEN it propagates unchanged out of `generate_case_summary`
- AND `sync.py`'s existing warning path handles it exactly as before this
  change

### Requirement: Pathological Tool-Input Failures Propagate as Exceptions

WHEN `tool_choice` forces a specific tool but the API cannot produce valid
input for it (e.g. context overflow), the system MUST let this surface as
an API-level exception. It MUST NOT catch this case and return malformed or
default data in its place.

#### Scenario: Forced tool call fails at the API level

- GIVEN a request with forced `tool_choice` cannot be fulfilled by the API
  (e.g. due to context overflow)
- WHEN the API call is made
- THEN an exception is raised and propagates out of the call site
- AND no malformed or silently-degraded output is returned in its place
