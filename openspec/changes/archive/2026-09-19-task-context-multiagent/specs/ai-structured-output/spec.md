# Delta for AI Structured Output

## MODIFIED Requirements

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
