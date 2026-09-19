# Archive Report: prompt-caching

**Change**: prompt-caching (Change 1 of 4 in MAGNA AI-layer modernization initiative)
**Archived**: 2026-09-17
**Status**: Complete — PASS WITH NOTES
**Artifact Store**: hybrid (OpenSpec + Engram)

## Executive Summary

Prompt caching for `_detect_relevant_modules` (`ctx task`) has been successfully implemented, tested, verified, and archived. The change restructures the module-detection prompt into a cacheable system prefix (module listing + PROYECTO.md) and a variable user turn, enabling repeated `ctx task` runs on the same project within the cache TTL to reuse cached input at ~10% cost. Implementation complete: 29/29 tests pass (10 new + 19 pre-existing, zero regressions). One explicit non-blocking manual follow-up remains: a human with ANTHROPIC_API_KEY should run two consecutive ctx task calls and confirm cache_read_input_tokens > 0 on the second (could not be automated in this environment).

## Archived Artifacts

All artifacts have been moved from `openspec/changes/prompt-caching/` to `openspec/changes/archive/2026-09-17-prompt-caching/`:

| Artifact | Type | Status |
|----------|------|--------|
| proposal.md | Design document | Complete |
| design.md | Technical design | Complete |
| specs/ai-prompt-caching/spec.md | Requirement specification (NEW domain) | Complete — synced to main spec tree |
| tasks.md | Implementation tasks | 11/13 complete (Phase 5 tasks are verify-owned, non-blocking) |
| verify-report.md | Verification summary | Complete — PASS WITH NOTES |
| exploration.md | Research/findings | Complete |
| state.yaml | Phase lifecycle | Complete |
| archive-report.md | This document | Complete |

## Specs Merged

**New domain created**: `openspec/specs/ai-prompt-caching/spec.md`

The delta spec from `openspec/changes/prompt-caching/specs/ai-prompt-caching/spec.md` was a full spec (not a delta merge), and was copied directly to the main spec tree. This establishes the canonical source of truth for all future implementations of prompt-caching across AICLI.

**Requirements coverage** (7 requirements, 13 scenarios):
- Cacheable System Prefix (3 scenarios)
- Deterministic Module Listing Order (1 scenario)
- Output Format and Behavior Preservation (1 scenario)
- Cache Effectiveness Observability (2 scenarios)
- Graceful Degradation Below Cache Threshold (1 scenario)

All offline-testable scenarios have passing unit tests. The two scenarios requiring live API round-trips (cache-read observability and below-threshold graceful degradation) are design-verified but not independently tested offline.

## Implementation Details

**Changed files**:
- `aicli/commands/task.py` (+24/-9 lines in core function, +33 net with imports/logging)
- `tests/test_prompt_caching.py` (182 lines, new file)

**Key changes**:
1. Module query now includes `ORDER BY Module.id` for deterministic listing order
2. Prompt split into stable `system` array (module listing + PROYECTO.md + `cache_control: {"type": "ephemeral"}`) and variable user turn (task_desc, file_context, JSON instruction)
3. Cache usage logged via `logging.info` after each API call, showing `cache_creation_input_tokens` and `cache_read_input_tokens`
4. Preserved: `model="claude-sonnet-5"`, `thinking={"type": "adaptive"}`, JSON output format, module filtering

**Testing**:
- Total: 29/29 tests pass (19 pre-existing + 10 new)
- Exit code: 0
- Covered test cases:
  - Deterministic query ordering (2 tests)
  - System block structure and cache_control presence (1 test)
  - Prefix purity: task_desc absent from system, present in user turn (1 test)
  - Listing/PROYECTO.md presence in system block (1 test)
  - Byte-identical system block across different task descriptions (1 test)
  - Contract preservation: model/thinking/JSON parse unchanged (2 tests)
  - Cache usage field handling when None (2 tests)

## Verification Findings

**Verdict**: PASS WITH NOTES

**Completeness**: All implementation tasks (Phases 1–4) complete and verified.

**Phase 5 (Non-blocking Follow-Ups)**:
- **5.1 Live cache-effectiveness check**: NOT EXECUTABLE in verify environment (no ANTHROPIC_API_KEY). Recorded as explicit manual follow-up, not a blocker. A human with API access should run two consecutive `ctx task` calls on an unchanged project within 5 minutes and confirm `cache_read_input_tokens > 0` on the second call.
- **5.2 Real prefix token-size estimate**: EXECUTED. Character-count approximation (~3.5–4 chars/token) on synthetic listings:
  - Realistic project (25 modules + content snippets + ~1,000-char PROYECTO.md): ~2,270–3,560 estimated tokens
  - Minimal project (5 modules, no content, no PROYECTO.md): ~118 estimated tokens
  - Conclusion: Non-trivial projects clear the ~1,024-token Sonnet minimum with comfortable margin; small projects legitimately fall below and exercise graceful degradation

**Spec Compliance**: All offshore-testable requirements pass. Design-level verification of graceful degradation consistent with Anthropic's documented behavior (silent ignore when below threshold).

**Scope Integrity**: Diff touches only `aicli/commands/task.py` and new `tests/test_prompt_caching.py`, matching stated scope. No scope creep. (Note: working tree has pre-existing uncommitted changes to knowledge/ files, pre-dating this SDD session; these are not part of this change.)

**Issues**:
- CRITICAL: None
- WARNING: None
- SUGGESTION: Phase 5.1 (live cache-read confirmation) remains open; recommend executing it post-archive while it is cheap and closes the one scenario automated testing cannot cover.

## Dependencies and Blockers

**Dependencies**: None. Uses installed Anthropic SDK; `cache_control` and `system` arrays are standard Messages API fields.

**Blockers resolved**:
- Ordering-key contradiction between initial spec (ORDER BY Module.name) and design (ORDER BY Module.id) was caught and corrected during spec phase; design choice (Module.id) verified as stable across re-indexing.
- All other findings from proposal/design/spec/apply/verify phases integrated.

**Blocks next change**: This change unblocks `structured-tool-output` (change 2 of 4), which depends on prompt-caching being archived.

## Task Completion Matrix

| Phase | Task | Status | Evidence |
|-------|------|--------|----------|
| 1 | Deterministic ordering (RED) | [x] | test_order_by_module_id_produces_ascending_sql |
| 1 | Deterministic ordering (GREEN) | [x] | task.py:134 includes .order_by(Module.id) |
| 2 | System prefix structure (RED) | [x] | test_system_cache_control_structure |
| 2 | Prefix purity (RED) | [x] | test_task_desc_absent_from_system_present_in_messages |
| 2 | Listing/PROYECTO presence (RED) | [x] | test_listing_proyecto_md_in_system_block |
| 2 | Byte-identical prefix (RED) | [x] | test_system_byte_identical_across_different_task_desc |
| 2 | System prefix split (GREEN) | [x] | task.py:21-67 restructured, system_blocks list + cache_control |
| 3 | Cache observability (RED) | [x] | test_logs_cache_usage_when_present |
| 3 | Cache observability (GREEN) | [x] | task.py logging.info after messages.create |
| 4 | Contract preservation (RED/GREEN) | [x] | test_model_thinking_unchanged, test_json_parse_and_filter_by_name |
| 5.1 | Live cache check | [ ] | Deferred to manual post-archive (no API key in environment) |
| 5.2 | Prefix token estimate | [x] | Executed via char-count approximation; 2.2x–3.5x above threshold for typical projects |

**Stale checkbox reconciliation**: Phase 5 tasks (5.1, 5.2) are explicitly "owned by sdd-verify" and "non-blocking by design" per tasks.md. 5.1 is genuinely not yet executable (no API key); 5.2 was executed via estimation. Both are accurately marked as non-blocking deferred items in the archived tasks artifact. No stale implementation-task checkboxes remain.

## Final State Authority Ranking

Per the SDD Archive skill specification, facts are ranked as follows (most to least authoritative):

1. **Native review authority**: Not applicable (no native review executed; delivery strategy was single-pr auto without explicit review gate)
2. **Persisted tasks artifact**: tasks.md (archived) shows all implementation phases complete with checkmarks; Phase 5 correctly marked as verify-owned non-blocking items
3. **Explicit final-state facts from orchestrator launch prompt**: Confirm status=passed-with-notes, 29/29 tests pass, implementation complete, one explicit non-blocking manual follow-up
4. **verify-report snapshot**: Confirms PASS WITH NOTES, all offline tests pass, Phase 5.1 not executable, Phase 5.2 executed via estimation

**Contradictions**: None found. All sources agree on completion status and the single non-blocking follow-up.

## Open Follow-Ups

**Manual verification item (Phase 5.1 — explicitly non-blocking per original design)**:

A human with `ANTHROPIC_API_KEY` and access to a real AICLI project DB should execute the following minimal harness to close the final observability loop:

```bash
# On a project with documented modules (10+ recommended)
ctx task "refactor the authentication module"
# Note: cache_creation_input_tokens from logs (1st run)
# Wait < 5 minutes, then:
ctx task "add logging to the API layer"
# Confirm: cache_read_input_tokens > 0 in logs (2nd run should show cache hit)
```

**Recommendation**: Execute this while fresh (same session, < 1 hour) to validate that the exact cache shape materializes in production. Low cost (~0.5 cents), high confidence gain. Not a blocker for archiving, as per the original proposal and task design.

**Follow-up tracking**: This item should be tracked separately from the main change archive (e.g., as a postscript in the user's session memory or a follow-up SDD task list) rather than as part of this closed change.

## Rollback Plan

**Revert the diff** — complete and sufficient:
- No schema change, no migration, no new dependency (SDK already installed), no config key, no on-disk artifact
- Anthropic caches are server-side with 5-minute default TTL; reverting stops writing/reading them; already-paid writes are sunk cost and self-expiring
- No cleanup step required
- Pre-existing tests remain unaffected; new tests can be excluded from CI if desired

## Archive Integrity Checklist

- [x] All artifacts copied to `openspec/changes/archive/2026-09-17-prompt-caching/`
- [x] Delta spec merged into main spec tree (`openspec/specs/ai-prompt-caching/spec.md`)
- [x] Archived artifacts include proposal, design, specs, tasks, verify-report, exploration, state.yaml
- [x] No unchecked implementation tasks remain in archived tasks.md (Phase 5 correctly marked as verify-owned, non-blocking)
- [x] Archive report written and archived
- [x] Active `openspec/changes/prompt-caching/` folder is now superseded by archive (ready for cleanup by user/pipeline)
- [x] This change unblocks `structured-tool-output` (next in sequence)

## Conclusion

The `prompt-caching` change is complete, verified, and archived. All implementation and verification work has been successfully closed. The one remaining manual follow-up (Phase 5.1 live cache-read confirmation) is explicitly non-blocking per the original proposal and has been documented as a postscript for execution with API access.

**Next change in sequence**: `structured-tool-output` (change 2 of 4, MAGNA AI-layer modernization initiative)

---

**Archive report created**: 2026-09-17
**Archive path**: `openspec/changes/archive/2026-09-17-prompt-caching/`
**Status**: Ready for commit and delivery
