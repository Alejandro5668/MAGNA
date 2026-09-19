# Delta for AI Module Prefilter

## MODIFIED Requirements

### Requirement: Semantic Top-N Prefilter

WHEN a project has more than 20 documented modules and the vector collection
is available, `run_task_graph` (`task_graph.py`) MUST query the collection
for the 20 modules most semantically similar to `task_desc` and MUST build
the candidate set fed to the Detective node using only those modules,
unioned with any module pinned via `--file`. It MUST NOT pass the full
module catalog as the Detective's candidate set in this case.
(Previously: performed inside `_detect_relevant_modules` (`task.py`), the
call site this change deletes.)
(Reason: `_detect_relevant_modules` is deleted; `query_modules()`'s top-20
behavior and the `--file` union move unchanged into `run_task_graph`, which
now seeds the shared candidate state consumed by all 4 graph nodes, per
`ai-task-multiagent`.)

#### Scenario: Large project sends only top-20 plus pinned module to candidates

- GIVEN a project with 150 documented modules and no `--file` argument
- WHEN `ctx task` runs `run_task_graph` with a given `task_desc`
- THEN the resulting `candidates` list contains at most 20 modules
- AND every listed module was returned by the semantic query

#### Scenario: File-pinned module is always included

- GIVEN a project with 150 modules and a `--file` argument resolving to a module outside the top-20 semantic results
- WHEN `run_task_graph` builds `candidates`
- THEN the pinned module is present in `candidates` in addition to the top-20 results
- AND the caller's original `modules` list is not mutated

### Requirement: Graceful Degradation

IF a project has 20 or fewer documented modules, OR the Chroma collection or
query fails for any reason, `run_task_graph` MUST fall back to the full
unfiltered module list as the candidate set and MUST NOT raise an error or
block `ctx task` execution.
(Previously: the fallback was performed inside `_detect_relevant_modules`.)
(Reason: same relocation as Semantic Top-N Prefilter — the call site moves
into `run_task_graph` per `ai-task-multiagent`, the fallback behavior does
not change.)

#### Scenario: Small project skips prefilter

- GIVEN a project with 15 documented modules
- WHEN `run_task_graph` runs
- THEN the full list of 15 modules is used as `candidates` without querying Chroma

#### Scenario: Chroma failure does not block task execution

- GIVEN a project with 150 modules and a Chroma collection that raises an exception on query
- WHEN `run_task_graph` runs
- THEN it proceeds using the full unfiltered module list as `candidates`
- AND no exception propagates to the caller
