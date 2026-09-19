# Delta for AI Prompt Caching

## MODIFIED Requirements

### Requirement: Cacheable System Prefix

The module-detection call MUST place its content — the module listing
(name, description, file path, first-300-chars doc snippet per
`Module`, narrowed to a task-relevant top-N subset when the
`ai-module-prefilter` semantic prefilter is active) and the full
`PROYECTO.md` text — in the request's `system` array as a single text
block carrying `cache_control: {"type": "ephemeral"}`. The call MUST
place all variable content (task description, optional file hint, and
the JSON output instruction) in the `messages` user turn, positioned so
it never precedes the cached `system` block in the request. Unlike
`PROYECTO.md`, the module-listing portion of this cached block is no
longer guaranteed identical across calls with different `task_desc`
values on large projects, because the prefilter selects the listing's
contents based on `task_desc`; this is a deliberate, accepted tradeoff
(see the scenario below).
(Previously: required the entire `system` array content, including the
module listing, to be identical across calls regardless of `task_desc`.)

#### Scenario: Repeated call on an unchanged project shares an identical prefix

- GIVEN a project whose modules and `PROYECTO.md` have not changed since the last `ctx task` run, and the same `task_desc` is used
- WHEN `_detect_relevant_modules` is invoked twice within the cache TTL
- THEN both requests' `system` array content is byte-for-byte identical
- AND the second request's `response.usage.cache_read_input_tokens` is greater than zero

#### Scenario: Task description may vary the cached module-listing portion; PROYECTO.md portion never varies

- GIVEN two calls with different `task_desc` values but the same modules and `PROYECTO.md`
- WHEN both calls build their prompt
- THEN the `system` array's module-listing portion MAY differ between the two calls, reflecting the task-relevant top-20 subset selected for each `task_desc`
- AND the `system` array's `PROYECTO.md` portion MUST remain byte-for-byte identical between the two calls regardless of `task_desc`
- AND only the `messages` user-turn content is otherwise variable

(Reason: `module-semantic-prefilter` deliberately narrows the cached
listing to a task-relevant top-20 subset for large projects, so that
`_detect_relevant_modules` sends fewer, more relevant modules instead
of the full catalog. This structurally breaks the prior "system block
identical regardless of task_desc" invariant for the listing portion.
The tradeoff was reviewed and accepted by the user: the 5-minute
ephemeral cache TTL rarely spans two `ctx task` runs on the same
project, so the lost cross-task cache read is largely theoretical,
while the token-count reduction from sending 20 modules instead of
100+ is certain. `PROYECTO.md`'s portion of the block is unaffected by
the prefilter and continues to be fully cacheable across task
descriptions.)

#### Scenario: Empty module list never reaches this function

- GIVEN `_execute_task` has loaded zero modules for the current project
- WHEN `_execute_task` runs its module-count check (`task.py:136-138`)
- THEN it returns early with a warning
- AND `_detect_relevant_modules` is never invoked with an empty `modules` list
