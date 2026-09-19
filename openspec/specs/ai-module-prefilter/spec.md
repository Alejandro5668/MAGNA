# AI Module Prefilter Specification

## Purpose

Defines the semantic top-N narrowing of documented modules fed into
`_detect_relevant_modules`'s prompt, backed by a local embedded Chroma
vector collection per project, so large projects avoid sending a
full-catalog listing while correctness is preserved via a `--file` pin
union and graceful fallback to today's full-list behavior.

## Requirements

### Requirement: Per-Project Vector Collection

The system MUST maintain a local, embedded Chroma vector collection
dedicated to each project, storing one embedding document per `Module`
row keyed by `Module.id` as the Chroma document id. The client MUST
disable anonymized telemetry.

#### Scenario: Collection created for a new project
- GIVEN a project has no existing Chroma collection
- WHEN the first module-related write occurs for that project
- THEN a project-scoped Chroma collection is created and the module is upserted into it

#### Scenario: Telemetry disabled
- GIVEN the Chroma client is initialized
- WHEN it is configured
- THEN anonymized telemetry MUST be disabled

### Requirement: Embedding Text Composition

Each module's embedding document MUST be composed as
`f"{name}: {description}"`, using only `Module.name` and
`Module.description`. No file content or documentation snippet MAY be
read to build the embedding text.

#### Scenario: Upsert uses name and description only
- GIVEN a `Module` row with a name and description
- WHEN it is upserted into the vector collection
- THEN the stored document text is exactly `f"{name}: {description}"`
- AND no file at `content_path` or `file_path` is read during the upsert

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

### Requirement: Lazy Reconciliation

On each query, the system MUST diff the vector collection's stored
module ids against the currently loaded `Module.id`s and upsert
whatever ids are missing or stale before executing the semantic query.

#### Scenario: Pre-existing project self-heals with no prior embeddings
- GIVEN a project indexed before this change exists, with modules in SQLite but none in the Chroma collection
- WHEN the first `ctx task` run after upgrade occurs
- THEN missing modules are upserted into the collection before the query runs
- AND the query returns correctly narrowed results with no manual re-index step

#### Scenario: Partially failed prior upsert self-heals
- GIVEN a collection missing embeddings for a subset of currently loaded modules due to a prior failed upsert
- WHEN `_detect_relevant_modules` runs
- THEN the missing subset is upserted before the query executes

### Requirement: Upsert Coverage at All Module Write Sites

The system MUST upsert into the vector collection at every code path
that writes or updates a `Module` row: `init.py`'s `_save_modules` and
`_update_project`, `file_cmd.py`'s `_save_zone_modules`, and
`sync.py`'s `_sync_impl` new/updated-module branch.

#### Scenario: New module written via init is embedded
- GIVEN `ctx init` creates a new `Module` row via `_save_modules`
- WHEN the write completes
- THEN the corresponding embedding is upserted into the vector collection

#### Scenario: Module updated via sync is re-embedded
- GIVEN `ctx sync` updates an existing `Module`'s description via `_sync_impl`
- WHEN the write completes
- THEN the vector collection reflects the updated embedding for that module id

### Requirement: Frozen Binary Packaging

The PyInstaller-compiled `ctx.exe` MUST bundle `chromadb` and its
runtime dependencies such that a `ctx task` invocation against the
frozen binary starts and completes successfully, with no
missing-module or native-library errors. This is a blocking,
verifiable requirement for this change, not deferred to a follow-up.

#### Scenario: Frozen exe runs ctx task end to end
- GIVEN `ctx.exe` has been built via PyInstaller with `chromadb` bundled
- WHEN `ctx.exe task "<description>"` is executed against a real project
- THEN the process starts without import or native-library errors
- AND it completes a full `ctx task` run to output
