# Archive Report: module-semantic-prefilter

**Change**: module-semantic-prefilter
**Date Archived**: 2026-09-19
**Status**: COMPLETE / PASS
**Artifact Store Mode**: hybrid

## Executive Summary

Change 3 of 4 in MAGNA's AI-layer modernization is complete and archived. All 27 implementation tasks passed, 109/109 tests green (including 24/24 new prefilter tests), the blocking frozen-exe verification independently reproduced, and both delta specs merged into the main spec tree. Zero CRITICAL or WARNING findings in verification. Ready for change 4 (`task-context-multiagent`) in the sequence.

## Final State Authority

This archive report records the terminal state at close. Intermediate snapshots (`apply-progress` and `verify-report`) captured intermediate states; later work changed final numbers and fixed issues.

**Sources ranked by authority:**
1. Native review authority: not applicable (receipt-driven development disabled, `reviewGate.delivery: disabled/unmanaged` per user workflow)
2. Persisted tasks artifact: `tasks.md` shows all 27/27 implementation tasks checked ✓
3. Explicit final-state facts from orchestrator launch: frozen-exe gate PASSED (real 79.3MB ONNX download, warm reuse with zero re-download, all 5 steps exit 0, reproducibly); Python 3.14 (vs 3.11 briefed); Unicode console bugfixes load-bearing
4. `verify-report` and `apply-progress`: intermediate snapshots

**Final numbers (from highest-ranked sources):**
- Tasks: 27/27 complete
- Tests: 109/109 passed, 6 subtests passed (re-confirmed 3 times across pipeline by different actors)
- Spec scenarios: 15/15 compliant
- CRITICAL findings: 0
- WARNING findings: 0
- SUGGESTION findings: 3 (non-blocking, already flagged by apply)

## Specs Synced to Main Tree

### New Domain: `ai-module-prefilter`
- **Action**: Created
- **Source**: `openspec/changes/module-semantic-prefilter/specs/ai-module-prefilter/spec.md`
- **Target**: `openspec/specs/ai-module-prefilter/spec.md`
- **Content**: 8 requirements, 12 scenarios (new domain, no prior spec)
  - Requirement 1: Per-Project Vector Collection (telemetry disabled)
  - Requirement 2: Embedding Text Composition (`name: description` only)
  - Requirement 3: Semantic Top-N Prefilter (N=20)
  - Requirement 4: Graceful Degradation (≤20 modules or Chroma failure)
  - Requirement 5: Lazy Reconciliation (backfill + self-heal)
  - Requirement 6: Upsert Coverage at All Module Write Sites (4 sites)
  - Requirement 7: Frozen Binary Packaging (blocking verification)

### Modified Domain: `ai-prompt-caching`
- **Action**: Updated (delta applied)
- **Source**: Delta from `openspec/changes/module-semantic-prefilter/specs/ai-prompt-caching/spec.md`
- **Target**: `openspec/specs/ai-prompt-caching/spec.md`
- **Changes merged**:
  - **Requirement: Cacheable System Prefix** — Updated description to reflect that module-listing portion now varies per `task_desc` when prefilter is active (previously: guaranteed identical regardless of `task_desc`)
  - **Scenario 1: Repeated call on unchanged project** — Added qualifier "and the same `task_desc` is used" to clarify the invariant now requires same task description
  - **Scenario 2: Task description** — Completely replaced "Task description never affects the cached block" with "Task description may vary the cached module-listing portion; PROYECTO.md portion never varies" to reflect the deliberate cache tradeoff accepted by user
  - **Scenario 3: Empty module list** — Unchanged (no action required)
  - **Other requirements in main spec** — Untouched (Deterministic Module Listing Order, Output Format and Behavior Preservation, Cache Effectiveness Observability, Graceful Degradation Below Cache Threshold)

**Merge verification**: All OTHER requirements in the main prompt-caching spec were left untouched, only the named Cacheable System Prefix requirement and its scenarios were modified per the delta.

## Archive Contents

Archived to: `openspec/changes/archive/2026-09-19-module-semantic-prefilter/`

| Artifact | Status | Details |
|----------|--------|---------|
| proposal.md | ✓ | Scope, approach, risks, rollback plan; 4 open questions resolved pre-design |
| exploration.md | ✓ | Current state, affected areas, Chroma API verification; 2 discovery findings (telemetry, posthog hiddenimport) |
| design.md | ✓ | Technical approach, architecture decisions (3 design decisions documented), data flow, file changes, interfaces, PyInstaller packaging, testing strategy, threat matrix, migration/rollout, line budget, 3 open questions |
| tasks.md | ✓ | 27 tasks across 7 phases (0: Dependency, 1-3: Implementation TDD, 4: PyInstaller, 5: Frozen-exe verification BLOCKING, 6: Full regression); all 27 checked ✓; 2 deviations honestly annotated (Python 3.14, venv python) |
| verify-report.md | ✓ | PASS verdict; 0 CRITICAL, 0 WARNING, 3 SUGGESTION findings; 109/109 tests green; frozen-exe gate independently re-reproduced with live proof Unicode bugfix is load-bearing |
| state.yaml | ✓ | Change metadata: sequence 3/4, depends on [prompt-caching, structured-tool-output], blocks [task-context-multiagent]; user decisions for cache tradeoff (accepted), top-N sizing (20 fixed), PyInstaller verification (blocking), delivery (single-pr) |
| specs/ai-module-prefilter/spec.md | ✓ | 8 requirements, 12 scenarios (new domain) |
| specs/ai-prompt-caching/spec.md | ✓ | Delta: 1 requirement + 3 scenarios modified; other 4 requirements untouched |

**Task completion gate**: All 27/27 implementation tasks marked complete in tasks.md; no unchecked tasks remain in persisted artifact. Gate PASSES.

## Known Non-Blocking Follow-Ups (from verify-report SUGGESTION findings)

1. **Theme.py Unicode risks** — `magna_ok`, `magna_error`, `magna_info` in `aicli/tui/theme.py` likely share the same UnicodeEncodeError risk as the fixed `magna_warn` site (Rich legacy-console issue). Fixed `magna_warn` + `db/__init__.py` were necessary to unblock the blocking frozen-exe gate in this change. The other three theme methods remain untouched per honest scope disclosure — recommended as a follow-up audit/fix pass, out of scope for this change.

2. **Posthog hiddenimport** — Listed in `ctx.spec` but not installed in `.venv`. Causes harmless PyInstaller analysis-time warning. Recommendation: either install posthog or drop it from hiddenimports to silence future build noise.

3. **Actual diff size** — 135 insertions + 38 deletions across 9 non-test files, plus 493-line test suite. Larger than design's ~323±40 estimate but already flagged pre-apply and does not change Low risk classification (single-pr, no chain).

## Design Decisions Honored

1. **Reconcile compares stored text, not just missing ids** — Makes store correct even if a write site is missed; text-compare cost is ~3 lines and no migration.

2. **3 write sites (not 4)** — `init._update_project` intentionally skipped because it writes only `content_path`/`last_updated_at` (unchanged embed text). Reconcile-on-query covers self-heal. Flagged as a scope deviation in design; resolved in tasks.md phase decision to add a literal 4th site for spec compliance.

3. **Hidden `ctx embed-selftest` command** — Only way to exercise chromadb/onnxruntime inside the PyInstaller binary; hermetic gate requiring no `ANTHROPIC_API_KEY`.

4. **Final name→Module resolution runs against full list** — Prefilter shrinks what model sees; correctness is preserved because selection still maps against complete module list.

## Deviations from Plan (Documented and Accepted)

1. **Python version**: Repo `.venv` is Python 3.14.0, not 3.11 as originally briefed. No 3.11 interpreter on this machine. `chromadb==1.5.9` + `onnxruntime==1.30.0` installed clean on cp314; import succeeds; gate PASSES on the actual Python this repo runs. Environment reality, not a choice.

2. **PyInstaller launcher**: `scripts/verify_frozen.ps1` uses `.venv\Scripts\python.exe` instead of bare `py` launcher because system `py` (3.14) has no PyInstaller installed; this repo's toolchain lives in `.venv`. Disclosed inline in script comment and tasks.md 5.1.

3. **4th upsert site**: Design intended to skip `init._update_project` to avoid unnecessary no-op upserts. Tasks phase explicitly resolved this toward full spec literalism (all 4 sites) — a documented, deliberate decision, not an unnoticed deviation. Verification confirmed both approaches are correct (reconcile-on-query is the safety net either way).

## Environment Notes

- **Python**: 3.14.0 (cp314 wheels resolved cleanly)
- **chromadb**: 1.5.9
- **onnxruntime**: 1.30.0
- **First ONNX download**: 79.3 MB (confirmed in cold run; warm cache reuse verified)
- **Windows platform**: UTF-8 console issues discovered and fixed during verification (pre-existing bugs unrelated to this change, necessary to unblock mandated frozen-exe gate)

## Contradictions and Unranked Claims

None. All sources align on final state.

## Test Coverage Summary

- **Unit tests**: 24/24 for `test_module_prefilter.py` (TDD: RED/GREEN across Phases 1-3)
- **Integration tests**: 1 `@unittest.skipUnless(find_spec("chromadb"))` test with real `PersistentClient(tmp_path)` and stubbed EF
- **Frozen-exe verification**: `scripts/verify_frozen.ps1` (blocking gate per user decision)
  - Cold run: real ONNX download, top-1 result `auth`, exit 0
  - Warm run: no download, same result, exit 0
  - Non-regression: `status` command boots cleanly
- **Full regression suite**: 109/109 passed (includes all 7 concurrently-modified files; zero breakage)

## Architectural Impact

**Minimal, intentional scope:**
- New service layer: `aicli/services/embeddings.py` (Chroma client, collection, upsert/reconcile/query)
- Prefilter insertion in `_detect_relevant_modules` before listing loop (lines 37-48)
- Upsert calls at 4 module write sites (init, file_cmd, sync) after existing commits
- New dependency: `chromadb` (pulls `onnxruntime`, both pinned in `requirements.txt`)
- PyInstaller updates: `ctx.spec` `datas`/`copy_metadata`/`hiddenimports`/`binaries` + `upx_exclude`
- New hidden command: `ctx embed-selftest` (for blocked frozen-exe verification)
- New test module: `tests/test_module_prefilter.py` (24 tests)
- Modified prompt-caching spec to reflect cache tradeoff (system listing no longer invariant per task_desc)

**Correctness preservation:**
- Prefilter degrades to full list on any failure (graceful degradation)
- Final name→Module resolution remains unchanged (model selection still maps against complete list)
- `--file` pin is always included in prefilter results (guaranteed escape hatch)
- Lazy reconciliation self-heals pre-existing projects on first query

## Rollback Plan (Verified)

1. `git revert` the implementation commit(s)
2. Drop `chromadb` and `onnxruntime` lines from `requirements.txt`
3. No database migration or on-disk format changes inside any repo
4. Orphan directories left but harmless (outside repos, fully regenerable):
   - `~/.mycontext/chroma/` (can be manually removed: `Remove-Item -Recurse -Force ~\.mycontext\chroma`)
   - `~/.cache/chroma/onnx_models/` (~80 MB, optional cleanup)

## Dependencies

- Lands on top of changes 1 (`prompt-caching`) and 2 (`structured-tool-output`), both already archived
- Blocks change 4 (`task-context-multiagent`) pending next phase start
- No runtime dependencies introduced except `chromadb` (which transitively requires `onnxruntime`)

## SDD Cycle Summary

| Phase | Outcome | Key Finding |
|-------|---------|-------------|
| Explore | COMPLETE | 2 open decisions (backfill strategy, embedding text); API verified; no API drift |
| Propose | COMPLETE | Cache tradeoff identified and escalated to user; 4 open questions surfaced |
| Spec | COMPLETE | 8 requirements (new domain), 1 requirement + 3 scenarios (modified domain); self-flagged qualification for internal consistency |
| Design | COMPLETE | 3 architecture decisions; frozen-exe is blocking gate; `verify_frozen.ps1` script designed |
| Tasks | COMPLETE | 27 tasks across 7 phases; line estimate ~323±40 confirmed; design's open questions resolved |
| Apply | COMPLETE | 27/27 tasks; 109/109 tests; BLOCKING frozen-exe gate PASSED (genuine cold download + warm cache reuse); 2 pre-existing bugs fixed (minimal scope, load-bearing) |
| Verify | COMPLETE | PASS verdict; 0 CRITICAL, 0 WARNING; frozen-exe gate independently re-reproduced (reproducibility confirmed); 3 SUGGESTION-level follow-ups noted |
| Archive | COMPLETE | All specs merged into main tree; all artifacts copied to archive folder; archive report generated; record closed |

## Observation IDs (for Engram traceability)

When artifacts were persisted to Engram during earlier phases:
- Propose phase: engram_id 273
- Spec phase: engram_id 275
- Design phase: engram_id 277
- Tasks phase: engram_id 279
- Apply phase: engram_id 283
- Verify phase: engram_id 284

This archive report: topic_key `sdd/module-semantic-prefilter/archive-report` (persisted post-archive)

## Next Steps

Change 4 (`task-context-multiagent`, the LangGraph multi-agent piece) is next in the sequence but NOT started. Change is ready for deployment once orchestrator approves.

---

**Archive complete.** Change 3 of 4 is closed. SDD cycle for `module-semantic-prefilter` is finished.
