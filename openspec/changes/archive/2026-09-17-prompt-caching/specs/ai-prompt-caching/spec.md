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

The module-detection call MUST place its stable content — the module
listing (name, description, file path, first-300-chars doc snippet per
`Module`) and the full `PROYECTO.md` text — in the request's `system` array
as a single text block carrying `cache_control: {"type": "ephemeral"}`. The
call MUST place all variable content (task description, optional file hint,
and the JSON output instruction) in the `messages` user turn, positioned so
it never precedes the cached `system` block in the request.

#### Scenario: Repeated call on an unchanged project shares an identical prefix

- GIVEN a project whose modules and `PROYECTO.md` have not changed since the last `ctx task` run
- WHEN `_detect_relevant_modules` is invoked twice within the cache TTL
- THEN both requests' `system` array content is byte-for-byte identical
- AND the second request's `response.usage.cache_read_input_tokens` is greater than zero

#### Scenario: Task description never affects the cached block

- GIVEN two calls with different `task_desc` values but the same modules and `PROYECTO.md`
- WHEN both calls build their prompt
- THEN the `system` array content is identical between the two calls
- AND only the `messages` user-turn content differs

#### Scenario: Empty module list never reaches this function

- GIVEN `_execute_task` has loaded zero modules for the current project
- WHEN `_execute_task` runs its module-count check (`task.py:136-138`)
- THEN it returns early with a warning
- AND `_detect_relevant_modules` is never invoked with an empty `modules` list

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

Restructuring the prompt MUST NOT change `_detect_relevant_modules`'s
observable contract: it MUST still return a JSON array of module name
strings parseable by the existing strict parse at `task.py:64-66`, MUST
still call `model="claude-sonnet-5"` with `thinking: {"type": "adaptive"}`,
and MUST NOT alter the wording of the module-selection instructions in a way
that changes selection accuracy.

#### Scenario: JSON parse succeeds unchanged

- GIVEN the restructured prompt is sent for a real task
- WHEN the response is received
- THEN `json.JSONDecoder().raw_decode` on the extracted text succeeds exactly as before
- AND the returned list contains only modules present in the input `modules` list

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
