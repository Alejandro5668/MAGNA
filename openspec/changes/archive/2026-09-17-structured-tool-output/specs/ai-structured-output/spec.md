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

Each of the 4 migrated call sites MUST send `tools=[...]` with exactly one
tool whose `input_schema` is a JSON Schema with top-level `type: "object"`,
and MUST set `tool_choice={"type": "tool", "name": <that tool's name>}` so
the model cannot reply in free-form prose.

#### Scenario: Model output is structurally forced

- GIVEN any of the 4 migrated call sites builds a request
- WHEN the request is sent to the Messages API
- THEN the request includes `tools` with one tool definition and
  `tool_choice` naming that exact tool
- AND the API response's content contains a `tool_use` block for that tool

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

Migrating `_detect_relevant_modules` to forced tool output MUST NOT alter
its existing `thinking: {"type": "adaptive"}` setting or the change-1
prompt-caching `system`-array/`cache_control` structure. This change
replaces only the output mechanism.

#### Scenario: Cached prefix and adaptive thinking survive migration

- GIVEN `_detect_relevant_modules` is migrated to `tools`/`tool_choice`
- WHEN a request is built
- THEN `thinking` is still `{"type": "adaptive"}`
- AND the `system` array still carries the cached module-listing/PROJETO.md
  block with `cache_control: {"type": "ephemeral"}` unchanged

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
