# Delta for AI Prompt Caching

## MODIFIED Requirements

### Requirement: Output Format and Behavior Preservation

Restructuring the prompt MUST NOT change `_detect_relevant_modules`'s
observable contract: it MUST still return only module names present in the
input `modules` list, MUST still call `model="claude-sonnet-5"` with
`thinking: {"type": "adaptive"}`, and MUST NOT alter the wording of the
module-selection instructions in a way that changes selection accuracy.
The call MUST send `tools=[...]` with a single tool whose `input_schema`
declares a string-array field of relevant module names, forced via
`tool_choice={"type": "tool", "name": <that tool's name>}`. Extraction MUST
read the matching `ToolUseBlock.input` directly as an already-parsed
`dict` and MUST NOT call `json.loads` or `json.JSONDecoder().raw_decode` on
the response.
(Reason: `structured-tool-output` replaces the prose-JSON + manual-parse
contract — `json.JSONDecoder().raw_decode` at `task.py:64-66`/`80-81` is
removed entirely — with a forced `tool_use` call, whose `ToolUseBlock.input`
is already a parsed dict. This eliminates the malformed-JSON failure mode
this call site had no safety net against, without touching the cached
`system` prefix, `thinking`, or model established by this spec.)
(Previously: required a JSON array of module name strings parseable by
`json.JSONDecoder().raw_decode` at `task.py:64-66`.)

#### Scenario: Tool input succeeds unchanged

- GIVEN the restructured prompt is sent for a real task
- WHEN the response is received
- THEN the forced tool's `ToolUseBlock.input` contains the module-name array
  directly, requiring no JSON parsing
- AND the returned list contains only modules present in the input
  `modules` list

#### Scenario: Cached system prefix and thinking config are unaffected

- GIVEN the call now sends `tools` and forced `tool_choice`
- WHEN the request is built
- THEN the `system` array still carries the cached module-listing block
  with `cache_control: {"type": "ephemeral"}` unchanged
- AND `thinking` is still `{"type": "adaptive"}`
- AND `model` is still `"claude-sonnet-5"`
