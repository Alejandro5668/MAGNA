# Archive Report — task-context-multiagent

**Archived**: 2026-09-19
**Change**: task-context-multiagent (change 4 of 4 — final piece of MAGNA's AI-layer modernization initiative)
**Status**: CLOSED — passed-with-notes, 0 CRITICAL open, all specs merged.

## Summary

Replaced `ctx task`'s two sequential single-shot Anthropic calls
(`_detect_relevant_modules`, `_generate_task_brief`) with one `StateGraph`
(`aicli/services/task_graph.py`): three parallel specialist nodes — Detective
de Módulos (LangChain `create_agent` ReAct loop with iterative lookup tools
`leer_doc_modulo`/`buscar_en_codigo` plus a terminal structured-response tool),
Historiador de Jira (keyword-overlap precedent search over `tickets.json`),
Vigía de Tests (content-scan test-coverage mapping) — fanning into one
Sintetizador node producing the final task brief.

## Implementation

- 32/32 tasks complete across 9 phases (dependency gate → foundation →
  Detective → Historiador/Vigía/Sintetizador → graph wiring → `task.py`
  integration → `graph-selftest` → PyInstaller packaging → regression fixups).
- New dependencies: `langgraph==1.2.11`, `langchain==1.4.2`,
  `langchain-anthropic==1.7.2` (pulled `anthropic` from `0.107.0` to `1.7.0` as
  a transitive bump — independently verified to cause zero regression in
  changes 1-3's code before this change's own work began).
- Blocking PyInstaller frozen-`MAGNA.exe` verification (`scripts/verify_frozen.ps1`,
  extended with a new `graph-selftest` hidden-command step) passed live,
  re-run twice: once at initial apply, once again after all Judgment Day
  fixes landed.

## Judgment Day — real project history, not an aside

After apply, the user explicitly requested Judgment Day (dual-blind
adversarial review, 2 independent judges) given this change's size and
architectural novelty — MAGNA's first LangChain/LangGraph integration.

**Round 1 finding (CRITICAL, corroborated by both judges, independently
verified by the orchestrator against installed vendor source):** the
Detective's original model config combined `ChatAnthropic(...,
thinking={"type":"adaptive"})` with `response_format=ToolStrategy(...)`.
`ToolStrategy` forces `tool_choice="any"` every turn
(`langchain/agents/factory.py`), but `langchain_anthropic` silently drops
that forced choice whenever `thinking` is enabled — a real, documented
Anthropic API incompatibility (`langchain_anthropic/chat_models.py:2492-2510`)
— emitting an unsuppressed `warnings.warn(...)` on every real `ctx task` run
and leaving loop termination unguaranteed.

**Fix**: `thinking` removed from the Detective's `ChatAnthropic(...)`
construction (that one instance only — verified not present anywhere else in
the Detective's model config; other Anthropic calls elsewhere in the
codebase were untouched since they don't combine `thinking` with forced tool
choice).

**Round 2 (scoped re-judgment):** confirmed the fix; also caught a
fix-caused gap — a third sibling spec file (`ai-prompt-caching`'s delta) was
left with stale contradictory `thinking={"type":"adaptive"}` text that
round 1's fix hadn't touched. Corrected directly by the orchestrator.

**Verdict: JUDGMENT: APPROVED ✅** — 0 critical findings remaining after
round 2.

**User then requested the 4 remaining WARNING/SUGGESTION findings also be
fixed** (not required by the protocol, but requested): two test-quality gaps
(a test named "unforced" that never asserted `tool_choice`, and a cache test
that only proved logging rather than the real `ChatAnthropic` request path),
a missing per-file size cap on the Detective's code-search tool (now shares
`_MAX_SCAN_FILE_BYTES` with Vigía's existing guard), and a leaked temp
directory in `graph_selftest.py` (now a proper `TemporaryDirectory` context
manager). All 4 fixed and TDD-verified — test count went from 130 → 134.

## Final Verification

- `sdd-verify` (post-Judgment-Day): passed-with-notes, 0 critical / 1 warning
  (test-coverage gap, non-blocking) / 1 suggestion.
- 134/134 tests, full suite, independently re-confirmed multiple times across
  the pipeline by different actors.
- Frozen-exe gate re-run live end-to-end (~7 min real PyInstaller build)
  after all fixes landed — PASS, all 6 steps.

## Specs Merged

- `openspec/specs/ai-task-multiagent/spec.md` — new domain (9 requirements),
  created.
- `openspec/specs/ai-structured-output/spec.md` — MODIFIED: "Forced Tool
  Choice for Structured Calls" (Detective's loop exempted from per-turn
  forcing) and "Caching and Thinking Configuration Preserved" (Detective's
  `ChatAnthropic` construction, `thinking` explicitly omitted with the
  Judgment-Day-discovered reason recorded in the spec text itself).
- `openspec/specs/ai-prompt-caching/spec.md` — MODIFIED: cached-prefix
  relocation to the Detective node, `thinking` omission.
- `openspec/specs/ai-module-prefilter/spec.md` — MODIFIED: `query_modules()`
  relocation from the deleted `_detect_relevant_modules` into
  `run_task_graph()`.

All 3 modified main specs verified self-consistent (no duplicate requirement
headers, no leftover stale `thinking={"type":"adaptive"}` references) before
this report was written.

## Process Note

This archive phase was interrupted mid-run by an unrelated API session-limit
error, after completing the `ai-task-multiagent` spec copy and merging all 3
MODIFIED deltas into their main specs, but before finishing the file copy
into this archive folder and before writing this report. The orchestrator
completed the remaining mechanical file copy and wrote this report directly
— no re-verification of the merge content was needed since it was already
correct and complete at the point of interruption.

## Milestone

This closes MAGNA's full 4-change AI-layer modernization initiative:
`prompt-caching` → `structured-tool-output` → `module-semantic-prefilter` →
`task-context-multiagent`. All 4 archived.
