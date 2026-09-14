# Proposal: QA Pipeline Verification Gaps

## Intent

The shipped pipeline can produce a verdict without testing anything. Repro runs
with zero DB/URL/browser context and may declare `not_reproduced` from a
text-only read of ticket history, short-circuiting verify + regression into
`dudoso`. DB/URL selection silently assumes a default ("usalo y no preguntes").
Security review only fires if a correction happens. Nothing checks whether the
fix duplicates existing code. Net effect: `qa_verified` is not trustworthy
evidence.

## Scope

### In Scope

- Pre-flight DB/URL confirmation before any stage runs — pure Python, zero
  tokens — reusing `needs_input` / `answer.json` / `resume_qa`.
- Repro receives real environment context (DB access rule + confirmed DB/URL)
  while keeping fix-diff isolation intact.
- New repro status `blocked` (could not attempt) split from `not_reproduced`
  (attempted, bug genuinely absent).
- New combined `review` stage — security + code-quality — that ALWAYS runs
  after `verify: pass`.
- Aggregator truth table consumes the security signal: severe finding ⇒
  `manual_review`, `reason: "security_finding_severe"`.

### Out of Scope

- New terminal verdicts or new badge vocabulary.
- Static analysers (semgrep/bandit) — deferred.
- Making `qa_verified` a gate; it stays advisory.
- Deeper Playwright/regression integration.

## Capabilities

### New Capabilities

- None — no new spec domain; the review stage is an ADDED requirement inside
  `qa-verification-stages`.

### Modified Capabilities

- `qa-orchestrator`: ADDED pre-flight environment confirmation; MODIFIED
  supersede (confirmed DB choice survives supersede; `review.json` joins the
  discarded stage artifacts).
- `qa-verification-stages`: MODIFIED Repro Stage Isolation (real attempt
  required, isolation preserved); ADDED repro `blocked` status; ADDED Review
  Stage Contract; MODIFIED Aggregator Sole Ownership (security input).
- `qa-correction-cycle`: MODIFIED Never Correct on Repro Failure (extends to
  `blocked`); security findings never open a correction cycle.
- `qa-status-surface`: ADDED review findings in the evidence digest; badge
  vocabulary explicitly unchanged.

## Approach

Two questions exploration left open are resolved here.

**One combined `review` stage, not two.** Security and quality read the same
input (fix diff + touched files) and neither is isolated from it, unlike repro.
Two stages would double context assembly, wall-clock and timeout surface for one
blocking and one advisory signal. Its JSON keeps them structurally separate
(`security`, `quality`) so the aggregator reads only security severity and a
quality finding can never move a verdict.

**Headless `claude -p` via the existing `invoke_stage()`.** SQLi detection here
is diff-scoped and semantic, and "reuse an existing pattern instead of
duplicating" has no deterministic tool at all. A linter would need per-language
install and config inside client repos. This adds no machinery: same prompt-file
+ JSON-contract path the other stages use, with a bespoke inlined prompt (no
skill dependency — none is installed).

Pre-flight is deliberately NOT an LLM call. "Always confirm" must be
deterministic; an agent asked to ask might not. It also avoids adding
`needs_input` to `REPRO_SCHEMA`, leaving that contract untouched.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `aicli/services/qa_prompts.py` | Modified | Repro gets `_DB_ACCESS_RULE` + config/answer blocks; new `build_review_prompt()`; `SECURITY_CHECKLIST` reused |
| `aicli/services/qa_runner.py` | Modified | Pre-flight gate, `run_review_stage()`, repro `blocked` branch, `aggregate()` security input, `_write_evidence_log()` review section |
| `aicli/services/qa_orchestrator.py` | Modified | `REVIEW_SCHEMA`, `_STAGE_ARTIFACTS` + `review.json`, persisted DB choice excluded from supersede |
| `aicli/commands/qa_cmd.py` | Unchanged | Existing resume path already covers the new pause |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Always-ask DB turns every sync into a blocking prompt | High | Confirm once per ticket, persisted across supersede; re-ask only when unrecorded or stale |
| Review stage adds a 3rd LLM invocation per run | Med | Runs only after `verify: pass`; combined, not split |
| Review false positive forces needless `manual_review` | Med | Only `severe` blocks; lower severities are informational |
| Touching `_STAGE_ARTIFACTS` / `_write_evidence_log` (shared, tested) | Med | Additive only; existing 101 tests are the regression net |
| Repro `blocked` reclassifies runs that used to read `dudoso` | Low | Intended correction; surfaced as `manual_review`, never a silent pass |

## Rollback Plan

All changes are additive behind existing structures. Revert the change's commits
to restore the prior pipeline; blackboard dirs written under the new shape are
forward-discarded by supersede on the next run. The existing QA kill switch
disables the pipeline entirely without a revert.

## Dependencies

- `qa-orchestrator-pipeline` archived (done — the 4 canonical specs exist).
- No new Python packages.

## Success Criteria

- [ ] No run reaches `dudoso` without recorded repro attempt evidence.
- [ ] No run executes a stage without a confirmed DB/URL choice.
- [ ] Every `verify: pass` is followed by a `review` stage artifact.
- [ ] A severe security finding yields `manual_review`, never `passed`.
- [ ] `qa-status-surface` badge vocabulary is byte-identical to today.

## Proposal question round

Could not ask interactively (delegated executor). Assumptions needing review:

1. **DB confirmation cadence** — assumed *once per ticket, persisted across
   supersede*. Literal "every run" is possible but makes each re-sync block on a
   human. Which do you want?
2. **Repro `blocked` destination** — assumed `manual_review`. Alternative:
   pause as `awaiting_input` and ask the user for access. Which?
3. **Quality findings are advisory only** — assumed they never affect the
   verdict, only the evidence digest. Should a severe duplication ever block?
4. **Review scope** — assumed it reviews the fix diff + touched files only, not
   the whole repo. Confirm?
5. **Severity authority** — assumed the review agent self-labels severity in its
   JSON. Do you want a hard-coded allowlist of blocking categories (SQLi,
   secrets, injection) instead?
