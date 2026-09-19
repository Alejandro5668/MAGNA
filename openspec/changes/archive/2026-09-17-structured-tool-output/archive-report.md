# Archive Report: Structured Tool Output

**Change**: `structured-tool-output`  
**Project**: aicli  
**Artifact Store**: hybrid  
**Archived**: 2026-09-17  
**Status**: PASS WITH WARNINGS  

## Executive Summary

Change 2 of MAGNA's AI-layer modernization initiative is complete and archived. All 25 core implementation tasks across Unit A and Unit B are checked and verified (53/53 test suite green, independently re-confirmed 3 times). The new `ai-structured-output` spec is created and synced to the main specs directory; the existing `ai-prompt-caching` spec is updated with its MODIFIED requirement delta. Two delta specs have been merged into the source of truth. The only open item is the pre-acknowledged manual live-environment smoke test (X1/X2), which cannot run without a real project and `ANTHROPIC_API_KEY` — documented as a manual follow-up for the user post-merge, consistent with how the prior change-1 (`prompt-caching`) handled the same limitation.

## Completeness Status

### Implementation Tasks

- **Unit A** (`_detect_relevant_modules` tool migration): 10/10 tasks checked
- **Unit B** (retry extraction + 3 call-site migrations + deletions): 15/15 tasks checked
- **Cross-Cutting** (X1/X2 live-environment smoke): 0/2 checked, explicitly-scoped manual follow-ups, not core implementation work

**Total**: 25/25 core implementation tasks complete. X1 and X2 are documented as unchecked by design — they require a real project, Jira integration, and `ANTHROPIC_API_KEY`, unavailable in any automated phase's sandbox. Per the Decision Gate table, live-environment verification failures are WARNINGS for non-core tasks, not CRITICAL blockers.

### Test Execution Summary

Command: `.venv\Scripts\python.exe -m pytest tests/ -v --ignore=tests/test_commands.py`

**Result**: 53 passed in 1.80s, zero failures, zero errors, zero network calls.

Composition:
- 33 pre-existing baseline tests (test_caller, test_jira_comments, test_prompt_caching baseline, test_tickets) — unchanged
- 20 new tests for Unit A and Unit B:
  - Unit A: 8 new tests (ContractPreservationTestCase, ExtractToolInputTestCase) in test_prompt_caching.py
  - Unit B: 12 new tests (baseline safety net, retry/backoff, tool-call migrations, dead-code removal, change-1 caching survival) in test_structured_output.py

**Note**: tests/test_commands.py excluded per explicit orchestrator instruction — independently confirmed to be a pre-existing broken file unrelated to this change (fails at collection, not touched).

### Specification Compliance

**AI Structured Output** (NEW domain, 7 requirements):
- Forced Tool Choice for Structured Calls — PASS
- No Manual JSON Parsing of Tool Output — PASS
- Array-Shaped Output Wrapped in Object — PASS
- Caching and Thinking Configuration Preserved — PASS
- Dead JSON-Repair Code Removed — PASS
- Structural Guarantee Removes Parse-Failure Fallback — PASS
- Pathological Tool-Input Failures Propagate as Exceptions — PASS

Each requirement has matching test coverage with real assertions (not tautologies).

**AI Prompt Caching** (MODIFIED requirement: "Output Format and Behavior Preservation"):
- Requirement re-pinned to tool-input extraction while preserving cached `system` prefix, `thinking`, and model — PASS
- Verified unaffected by Unit B (which never touches task.py) — PASS

## Spec Merge Summary

### New Spec Created
- **Domain**: `ai-structured-output`
- **Path**: `openspec/specs/ai-structured-output/spec.md`
- **Action**: Direct copy (no prior main spec existed; delta is a full spec)
- **Status**: Created and verified

### Existing Spec Modified
- **Domain**: `ai-prompt-caching`
- **Path**: `openspec/specs/ai-prompt-caching/spec.md`
- **Requirement Modified**: "Output Format and Behavior Preservation"
- **Old Content**: Required parsing via `json.JSONDecoder().raw_decode()` at task.py:64-66
- **New Content**: Tool-input extraction via `_extract_tool_input()` reading `ToolUseBlock.input` directly; required `tools` parameter and forced `tool_choice`; preserved cached `system`-array and `thinking`
- **Other Requirements Preserved**: Cacheable System Prefix, Deterministic Module Listing Order, Cache Effectiveness Observability, Graceful Degradation Below Cache Threshold — all untouched
- **Status**: Updated and verified

## Archive Contents

All artifacts from `openspec/changes/structured-tool-output/` have been copied to `openspec/changes/archive/2026-09-17-structured-tool-output/`:

- ✅ `proposal.md` — Intent, scope, approach, risks, rollback plan, dependencies
- ✅ `design.md` — Technical approach, architecture decisions, data flow, testing strategy, file changes
- ✅ `tasks.md` — 25 implementation tasks (A1-A10, B1-B15), 2 cross-cutting manual tasks (X1-X2)
- ✅ `verify-report.md` — PASS WITH WARNINGS, 53/53 tests green, TDD compliance 6/6
- ✅ `state.yaml` — Execution timeline and phase progress log
- ✅ `exploration.md` — Current state analysis, SDK facts, risks, readiness
- ✅ `specs/ai-structured-output/spec.md` — Full 7-requirement spec for new domain
- ✅ `specs/ai-prompt-caching/spec.md` — MODIFIED delta with updated requirement block

## Change Process History

### Orchestrator-Level Corrections During Lifecycle

Two corrections were made during the design review phase by the orchestrator, before apply:

1. **False "spec gap" claim struck** (design check 3): The design initially claimed `specs/ai-prompt-caching/spec.md` (the required MODIFIED delta) was missing from the change folder. This was verified false in orchestrator gate — the file existed and was complete. Corrected without requiring a re-run of `sdd-design`.

2. **Line-budget arithmetic error corrected** (design check 4): The original draft summed Unit B's five line-count components as ≈366 (B total) and single-PR as ≈491. The orchestrator identified an addition error: the five components actually sum to ≈426 (B total, +60 for schema constants), and single-PR to ≈551 (+60). This correction strengthened the case for the pre-authorized A/B split (both units now exceed 400-line budget on their own) and was recorded in design.md's Review Workload Forecast section.

Both corrections are part of this change's real history, not omitted background.

### Delivery Strategy

- **Initial forecast**: `single-pr` at ~390-400 lines (proposal estimate predated retry-extraction and test-stub decisions)
- **Design forecast** (corrected): A ≈125 lines, B ≈426 lines, Single PR ≈551 lines
- **Actual Unit B** (measured): 216 (indexer.py) + 343 (new test file) = 559 lines (31% overage vs corrected forecast, 33% vs original forecast)
- **User pre-approval**: `size:exception` for Unit B (delivery strategy = exception-ok per state.yaml)
- **Result**: Both PRs delivered as planned; no schedule impact; no functional impact from size.

## Dependencies and Sequencing

- **Depends on**: Change 1 (`prompt-caching`) — shipped and archived at `openspec/changes/archive/2026-09-17-prompt-caching/`
- **Blocks**: Change 3 (`module-semantic-prefilter`) — next in queue, NOT started yet
- **Sequence**: 2 of 4 in MAGNA's AI-layer modernization initiative

## Final Verification State

### Passed Gates

1. **Task Completion Gate** — 25/25 core tasks checked; X1/X2 unchecked by design (manual live follow-up)
2. **Native Review Authority** — Not applicable (gentle-ai review mode not enabled; delivery = disabled/unmanaged per user configuration)
3. **Spec Compliance** — 7 ai-structured-output requirements + 1 ai-prompt-caching modified requirement all PASS
4. **TDD Compliance** — 6/6 checks passed; no tautologies; real assertions on real behavior
5. **Code Quality** — Zero manual JSON parsing found; all cleanup tasks complete; all 33 baseline tests unaffected

### Open Items

**WARNING: Manual Live-Environment Smoke Tests**

Tasks X1 and X2 remain unchecked:

- **X1**: Real `ctx task` run confirming cache behavior (1st call = write, 2nd+ = read) — cannot run without real project + Jira/API key
- **X2**: Manual smoke — `ctx init`, `ctx file <zona>`, `ctx task`, `ctx sync` — unchanged output shape end-to-end — cannot run without real project + API key

**Substitute Evidence**: Static verification and comprehensive unit test coverage (53/53 green) covering all three migrated call sites' payload shape, unwrapping, error-propagation contracts, and change-1 caching survival. Not a defect; a documented manual follow-up consistent with how change-1 handled the same limitation.

**Recommendation**: User should run these smoke tests manually on a real project post-merge before considering the change fully battle-tested.

### No Critical Issues

Zero CRITICAL findings. The PASS WITH WARNINGS verdict stands.

## Rollback Scope

Complete revert of the unified diff. No migration, no schema change, no data backfill, no new dependency, no config key, no on-disk format change. Module output shapes remain identical before and after.

## Next Steps for the User

1. **Post-merge manual verification** (if desired): Run X1/X2 live smoke tests on a real project with `ANTHROPIC_API_KEY` set
2. **Change 3 unblocked**: `module-semantic-prefilter` is now unblocked but NOT auto-started; user may initiate when ready

## Archive Authenticity

This report reflects the state of the change **at close**, per the Final-State Authority hierarchy. Intermediate snapshots (`verify-report`, `apply-progress`) are historical records of their respective points in time. All facts have been sourced from:

1. **Native review authority** (if applicable) — none in this case
2. **Persisted tasks artifact** — `tasks.md` shows 25/25 core tasks checked
3. **Explicit final-state facts in launch prompt** — incorporated above
4. **Intermediate snapshots** (lowest rank) — `verify-report` re-confirms 53/53 tests and X1/X2 unchecked/documented

The archive record is complete, accurate, and ready for future reference.
