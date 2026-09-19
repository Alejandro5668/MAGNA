# AI Task Multiagent Specification

## Purpose

Defines the `StateGraph`-based multi-agent orchestration that replaces
`ctx task`'s two blind, sequential single-shot calls
(`_detect_relevant_modules` → `_generate_task_brief`) with three parallel
specialist nodes fanning into one synthesis node, so the brief carries
module relevance, ticket precedent, and test-coverage signal together. New
capability — no prior spec exists for this domain.

## Requirements

### Requirement: Static Fan-Out/Fan-In Graph Topology

The system MUST orchestrate task-context generation via one `StateGraph`
with three parallel specialist nodes (Detective de Módulos, Historiador de
Jira, Vigía de Tests) connected via static `add_edge(START, node)` calls,
fanning into exactly one Sintetizador node. The graph MUST NOT use `Send`
for this fan-out, and all three specialists MUST run on every invocation
(never opt-in/conditional).

#### Scenario: All three specialists run on every task

- GIVEN `ctx task` invokes the graph for any task description
- WHEN the graph executes
- THEN Detective de Módulos, Historiador de Jira, and Vigía de Tests all
  run in the same superstep
- AND Sintetizador runs only after all three have completed

#### Scenario: Graph is compiled once per process

- GIVEN the graph module is imported
- WHEN `ctx task` is invoked multiple times in the same process
- THEN the compiled graph object is reused, not rebuilt, across invocations

### Requirement: Detective de Módulos Uses an Iterative Agent Loop

Detective de Módulos MUST use `create_agent` (from `langchain.agents`) with
tools for iterative module lookup (e.g. reading a module's doc, searching
code), replacing today's single-shot `_detect_relevant_modules`. It MUST
absorb the existing semantic top-N prefilter and `--file` candidate union
(`ai-module-prefilter`'s Semantic Top-N Prefilter and File-pinned module
requirements) as its input-preparation step. Its output MUST be a
`list[Module]` matching the exact shape `build_context()` consumes today.

#### Scenario: Output shape is unchanged for downstream consumption

- GIVEN Detective de Módulos completes its loop for a given task
- WHEN its output is passed to `build_context()`
- THEN `build_context()` receives a `list[Module]` with no shape change
  required on the consuming side

#### Scenario: Semantic prefilter and file pin still apply inside the node

- GIVEN a project with more than 20 documented modules and a `--file`
  argument outside the top-20 semantic results
- WHEN Detective de Módulos prepares its candidate set
- THEN the candidate set is the semantic top-20 unioned with the pinned
  module, per `ai-module-prefilter`'s existing invariants

### Requirement: Cache-Control Pass-Through in the Agent Loop

Detective de Módulos's `create_agent`-based loop MUST preserve the
`ai-prompt-caching` cacheable-prefix behavior for its stable context (the
module listing / semantic-prefiltered candidates plus `PROYECTO.md`): this
content MUST still be marked `cache_control: {"type": "ephemeral"}` such
that repeated invocations within the cache TTL register a cache read. The
requirement is the observable outcome; the exact mechanism by which
`create_agent`'s `system_prompt`/`model` configuration carries
`cache_control` through to the underlying API call is a design-level
decision.

#### Scenario: Repeated task run within cache TTL registers a cache read

- GIVEN a project whose modules and `PROYECTO.md` have not changed since
  the last `ctx task` run
- WHEN Detective de Módulos runs twice within the cache TTL for
  comparable task inputs
- THEN the second run's underlying API response reports
  `cache_read_input_tokens > 0`

#### Scenario: Cache write still occurs on the first run

- GIVEN the first `ctx task` run of a session for a given project
- WHEN Detective de Módulos's agent loop completes its first API call
- THEN `cache_creation_input_tokens` is non-zero for that call

### Requirement: Historiador de Jira Searches Full Ticket Corpus by Keyword Overlap

Historiador de Jira MUST search the full ticket corpus (via
`load_tickets()`) for precedent using keyword/substring overlap over each
ticket's `descripcion` and `motivo_reapertura` fields — NOT semantic or
Chroma-backed search. WHEN no ticket matches, it MUST degrade to an
explicit "no precedent found" output rather than raising an error.

#### Scenario: Matching precedent is surfaced

- GIVEN a past ticket's `descripcion` or `motivo_reapertura` shares
  keyword overlap with the current task description
- WHEN Historiador de Jira runs
- THEN its output cites that ticket as precedent

#### Scenario: No precedent degrades gracefully

- GIVEN no ticket in the corpus shares keyword overlap with the current
  task description
- WHEN Historiador de Jira runs
- THEN its output states explicitly that no precedent was found
- AND no exception propagates to the graph

### Requirement: Vigía de Tests Maps Coverage by Content-Scanning Test Files

Vigía de Tests MUST identify test coverage for candidate modules by
scanning test file contents for each candidate module's path stem — NOT by
filename-pattern matching between test files and module names, since a
single test file may exercise multiple unrelated modules (verified:
`tests/test_commands.py` smoke-tests 7+ unrelated command modules). WHEN no
covering test is found for a candidate module, it MUST render an
advisory-only "sin cobertura detectada" note and MUST NOT block or alter
module selection.

#### Scenario: Coverage found via content scan

- GIVEN a candidate module whose path stem appears in an `import`-like
  line inside a test file
- WHEN Vigía de Tests scans test file contents
- THEN that test file is named as covering the candidate module

#### Scenario: Missing coverage is advisory only

- GIVEN a candidate module with no test file referencing its path stem
- WHEN Vigía de Tests completes its scan
- THEN its output includes an advisory "sin cobertura detectada" note for
  that module
- AND module selection (Detective's output) is unaffected by this note

### Requirement: Sintetizador Reconciles Specialist Outputs Into One Brief

Sintetizador MUST reconcile the outputs of all three specialists into one
brief string, replacing today's `_generate_task_brief`. This brief MUST
land at the same consumption point as before: under `# Plan de
implementación` in `session_context.md` via `caller.py`.

#### Scenario: Brief lands at the same document location

- GIVEN Sintetizador produces a brief for a completed graph run
- WHEN `session_context.md` is generated
- THEN the brief string appears under the `# Plan de implementación`
  heading, exactly as `_generate_task_brief`'s output did before this
  change

#### Scenario: Brief is usable when a specialist yields nothing

- GIVEN Historiador de Jira found no precedent and Vigía de Tests found no
  coverage
- WHEN Sintetizador reconciles the three outputs
- THEN it still produces a non-empty, usable brief string

### Requirement: `--file` Pin Survives Both Union Points Unchanged

The `--file` pin logic MUST continue to work at both of its existing union
points: inside module candidate preparation (now inside Detective de
Módulos) and in `_execute_task`'s outer safety-net union. Neither union
point MAY be removed or bypassed by the graph-based Detective.

#### Scenario: Pinned file is present after both union points

- GIVEN `ctx task` is invoked with a `--file` argument
- WHEN the graph runs and `_execute_task` applies its outer safety-net
  union afterward
- THEN the module resolved from `--file` is present in the final
  `relevant` list passed to `build_context()`

### Requirement: Evidence/Attachment Analysis Remains Independent of the Graph

The existing evidence/attachment-analysis block in `_execute_task`
(image/Jira attachment description, producing `evidence_summary`) MUST
continue to run independently of the graph and MUST remain available to
Sintetizador/the brief.

#### Scenario: Evidence summary still reaches the brief

- GIVEN `_execute_task` has produced a non-empty `evidence_summary` from
  attachment analysis
- WHEN the graph runs afterward
- THEN Sintetizador's brief reflects the evidence summary's content

### Requirement: Frozen Binary Packaging

The PyInstaller-compiled executable MUST bundle `langgraph`, `langchain`,
and `langchain-anthropic` such that a `ctx task` invocation against the
frozen binary starts and completes successfully end to end, with no
missing-module or dynamic-import errors. This is a blocking, verifiable
requirement for this change, not deferred to a follow-up.

#### Scenario: Frozen exe runs ctx task end to end

- GIVEN the frozen executable has been built via PyInstaller with
  `langgraph`, `langchain`, and `langchain-anthropic` bundled
- WHEN `dist\MAGNA.exe graph-selftest` is executed
- THEN the process exits 0
- AND a subsequent `dist\MAGNA.exe task "<description>"` run against a
  real project completes a full `ctx task` run to output with no import
  or dynamic-import errors
