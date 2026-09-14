# Exploration: qa-pipeline-verification-gaps

## Current State

The shipped QA pipeline (`qa-orchestrator-pipeline`, verified 101/101 tests / 34/34 tasks, all 4 spec domains PASS, but **not yet archived** — its delta specs still live only under `openspec/changes/qa-orchestrator-pipeline/specs/`, not in `openspec/specs/`, which currently only has `jira-resume-context` and `ticket-history-store`) runs repro → verify → [regression] → aggregate → [corrector], driven by `aicli/services/qa_runner.py`, prompts in `aicli/services/qa_prompts.py`, blackboard I/O in `aicli/services/qa_orchestrator.py`, hidden re-entry point in `aicli/commands/qa_cmd.py`.

All 4 background-diagnosis findings were independently re-confirmed against current code (not trusted from the prior diagnosis):

1. **Repro is blind, short-circuit is real and deliberate.** `qa_prompts.build_repro_prompt()` (qa_prompts.py:121-154) gets only `ticket_id` + `ticket_history` — no `_DB_ACCESS_RULE`, no `_default_config_block()`, no `_answer_block()`, unlike `build_verify_prompt()` (qa_prompts.py:157-194), which gets all three. `qa_runner.run_pipeline()` lines 392-401 short-circuit straight to `aggregate()`/`_finalize()` the moment `repro.status in ("not_reproduced", "error")` — `verify_fn`/`regression_fn` never run. This matches existing "Never Correct on Repro Failure" + "Repro Stage Isolation" requirements exactly, and that isolation intent must be preserved.
2. **DB/URL is opportunistic-only, confirmed.** `_default_config_block()` (qa_prompts.py:77-92) literally says "usalo y no preguntes" when a default exists — only asks via `needs_input` when ambiguous.
3. **Security check is corrector-only, confirmed.** `SECURITY_CHECKLIST` (qa_prompts.py:101-110) is referenced exactly once, inlined only in `build_corrector_prompt()` (line 235). If `verify` passes on the first try, it never runs. `aggregate()` (qa_runner.py:223-241) has no security input at all.
4. **No code-simplification/pattern-reuse logic exists anywhere** — confirmed absent from all 4 pipeline files.

**Correction to the original framing on point 4**: neither `ponytail-review` nor a `simplify` skill is installed anywhere on this machine. Globbed both `C:\Users\alexp\.claude\skills\**\SKILL.md` (24 skills — sdd-*, judgment-day, go-testing, skill-creator/improver, branch-pr, issue-creation, chained-pr, cognitive-doc-design, comment-writer, work-unit-commits, aj-architecture-*, find-skills, skill-registry) and the project's own `.claude/skills/` (only `tui-design`). `.atl/skill-registry.md` also confirms `security-review` is absent, matching design.md's own decision 5. The premise "reuse this repo's own installed ponytail-review/simplify skill logic" does not hold today.

**New finding not in the original background**: `REPRO_SCHEMA`'s contract has **no `needs_input` field at all** — only `verify.json` and `correction_N.json` carry it, and `run_pipeline()` only checks those two. The ask to confirm DB "at the start of a run" can't be satisfied by the existing escape hatch as-is: it needs either a new zeroth pre-flight pseudo-stage reusing `_finalize_awaiting_input`/`resume_qa`, or adding `needs_input` to `REPRO_SCHEMA`. **Findings 1 and 2 are coupled** — giving repro real DB/browser context implies it also needs to know which DB to use — so they should be designed together, not as independent slices.

## Affected Areas

- `aicli/services/qa_prompts.py` — `build_repro_prompt()`, `_default_config_block()`, `SECURITY_CHECKLIST`, and a new code-quality prompt would all change.
- `aicli/services/qa_runner.py` — the short-circuit block (lines 392-401) and `aggregate()` (lines 223-241) are the exact hook points for a real repro attempt and a new security signal; `_write_evidence_log()` needs a new artifact if a dedicated stage is added.
- `aicli/services/qa_orchestrator.py` — a new `SECURITY_SCHEMA` constant and an addition to `_STAGE_ARTIFACTS` (line 37-40) if a dedicated stage is added, so supersede-reset discards it correctly.
- `aicli/commands/qa_cmd.py` — no direct change expected.
- `openspec/specs/` vs `openspec/changes/qa-orchestrator-pipeline/specs/` — relevant to the spec-placement decision below.

## Approaches

1. **Standalone new SDD change whose spec deltas target the same 4 existing domain names** (qa-orchestrator, qa-verification-stages, qa-correction-cycle, qa-status-surface) via `MODIFIED`/`ADDED` blocks.
   - Pros: matches OpenSpec's delta model; keeps requirement history traceable per domain; avoids proliferating domains for what's still one subsystem.
   - Cons: `qa-orchestrator-pipeline` was never archived, so there's no canonical `openspec/specs/{domain}/spec.md` yet to diff against — `sdd-spec` would have to treat the old change's still-open delta files as baseline.
   - Effort: Medium.
2. **Same as (1), plus archive `qa-orchestrator-pipeline` first.**
   - Pros: clean OpenSpec hygiene; the prior change is fully verified with no functional reason left to stay open.
   - Cons: adds one process step before this change can proceed cleanly; sequencing decision for the user, not something explore can execute.
   - Effort: Low (process-only).
3. **New 5th spec domain** (e.g. `qa-security-stage`) instead of amending the existing 4.
   - Pros: isolates the new stage's requirements if it becomes independently-versioned later.
   - Cons: over-fragments findings 1-3, which are pure `MODIFIED` behavior on existing requirements, not new capabilities.
   - Effort: Medium-High.

## Recommendation

**Approach 1+2 combined**: run `qa-pipeline-verification-gaps` as its own standalone change, with spec deltas as `MODIFIED`/`ADDED` blocks against the existing 4 domain names. Recommend archiving `qa-orchestrator-pipeline` before or alongside starting `sdd-propose`, so deltas target real `openspec/specs/` files rather than another change folder. For design: route a new security signal through the existing `manual_review` verdict with a new free-text `reason` (e.g. `"security_finding_severe"`) rather than a new terminal state — `reason` is already free text, so this stays additive and keeps `qa-status-surface`'s badge vocabulary unchanged.

## Risks

- Genuinely unresolved: whether `claude -p` can headlessly invoke any code-review/quality skill logic is untested here, since no such skill is installed. The original Spike S1's actual result isn't retrievable from any file on disk. Design phase must either re-spike or design gap 4 as a bespoke inlined prompt (same pattern as `SECURITY_CHECKLIST`), with no skill dependency assumed.
- Findings 1 and 2 are coupled — sequencing them as independent slices risks rework.
- `REPRO_SCHEMA` currently has no `needs_input` field; adding one changes a JSON contract other code assumes is absent today.
- Adding a security/quality stage touches `_STAGE_ARTIFACTS` and `_write_evidence_log()` — both shared, tested surfaces.
- The prior change sitting unarchived despite full verification is a minor process risk worth surfacing independently.

## Ready for Proposal

Yes, with one open decision for the user before/during `sdd-propose`: archive `qa-orchestrator-pipeline` first or not. The 4 gaps and hook points are concrete; the one true unknown (headless skill invocability) should be a design-phase spike, not a blocker.
