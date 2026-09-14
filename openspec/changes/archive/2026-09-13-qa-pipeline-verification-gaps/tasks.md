# Tasks: QA Pipeline Verification Gaps

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~900–1050 (production ~465–535 across 3 modified files: `qa_orchestrator.py` ~120, `qa_prompts.py` ~120, `qa_runner.py` ~225; tests ~350–500 in `test_qa_orchestrator.py` covering 7 unit groups + 3 integration groups + 7 threat-matrix RED tests) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR1 Env pre-flight → PR2 Repro isolation/blocked → PR3 Review stage (largest, likely over budget alone) → PR4 Shell-safety hardening + full regression |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

Note: this mirrors the precedent from the archived `qa-orchestrator-pipeline` chain, where the
review-stage-equivalent slice (PR3) also exceeded budget alone and was surfaced transparently rather
than scope-cut. `sdd-apply` must not start until the orchestrator resolves `single-pr` → explicit
`size:exception`, or the user picks a chain strategy (stacked-to-main / feature-branch-chain).

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Env pre-flight: persisted `env_context.json`, `env_preflight()`, ask-once-per-ticket | PR 1 | `.venv\Scripts\python.exe -m pytest tests/test_qa_orchestrator.py -k Env` | `ctx sync` on a fresh ticket, confirm one env prompt, resync reuses it | Delete `read/write/clear_env_context`, `_parse_env_answer`, `env_preflight`; revert `_STAGE_ARTIFACTS`/`_PERSISTENT_ARTIFACTS` |
| 2 | Repro isolation upgrade + `blocked` status + bounded re-ask | PR 2 | `.venv\Scripts\python.exe -m pytest tests/test_qa_orchestrator.py -k "Repro or Blocked"` | Manual `claude -p` repro invocation with a seeded `env_context.json`, confirm no diff/commit knowledge leaks | Revert `build_repro_prompt` signature/body; drop `_repro_blocked`, `REPRO_SCHEMA` enum addition |
| 3 | Combined `review` stage + aggregator security gate (largest; likely over 400 lines alone) | PR 3 | `.venv\Scripts\python.exe -m pytest tests/test_qa_orchestrator.py -k Review` | Manual `claude -p` review invocation on a throwaway `git init` repo, confirm read-only + correct verdict routing | Delete `run_review_stage`, `_review_diff`, `_review_applies`, `build_review_prompt`, `BLOCKING_SECURITY_CATEGORIES`; revert `aggregate()`/`_verdict` to pre-review signature (keyword-defaulted, additive) |
| 4 | Shell/subprocess hardening RED tests + full-suite regression | PR 4 | `.venv\Scripts\python.exe -m pytest tests/test_qa_orchestrator.py` (full file) | N/A — pure regression/hardening pass, no new user-facing behavior to demo | No production code added; revert only the added test cases |

## Phase 1: Env Pre-Flight Foundation (`qa_orchestrator.py`, `qa_runner.py`)

- [x] 1.1 RED: assert `_PERSISTENT_ARTIFACTS` disjoint from `_STAGE_ARTIFACTS`; assert `_reset_blackboard` preserves `env_context.json` across `trigger_qa`/`resume_qa`.
- [x] 1.2 GREEN: add `ENV_SCHEMA = "qa.env/1"`, `_ENV_CONTEXT_FILE`, `_PERSISTENT_ARTIFACTS = (_ENV_CONTEXT_FILE,)` in `qa_orchestrator.py`; exclude from `_reset_blackboard`'s loop.
- [x] 1.3 RED: `_parse_env_answer` — valid `db=…url=…` pair, missing half, newline/backtick injection, over-length input all rejected/handled.
- [x] 1.4 GREEN: implement `_parse_env_answer(value) -> tuple[str|None, str|None]` — strict extraction, no control chars, length cap.
- [x] 1.5 GREEN: implement `read_env_context(run_dir)`, `write_env_context(run_dir, *, db, url, source)`, `clear_env_context(run_dir)` — atomic writes.
- [x] 1.6 RED: `env_preflight` state machine — no context ⇒ select question; "Otro…" ⇒ text question; parsed answer ⇒ file written and `answer.json` consumed; existing context ⇒ no question, no answer touched.
- [x] 1.7 GREEN: implement `env_preflight(run_dir, ticket_id) -> tuple[dict|None, dict|None]`, question dict adds `"topic": "env"`.
- [x] 1.8 RED (integration, tmp `MYCONTEXT_HOME`): `resume_qa` after an env answer persists `env_context.json`; reused on next `trigger_qa`; asked exactly once per ticket.
- [x] 1.9 GREEN: wire `env_preflight()` into `run_pipeline()` before the first `_advance`; pause via existing `_finalize_awaiting_input`.

## Phase 2: Repro Isolation + Blocked Handling (`qa_prompts.py`, `qa_orchestrator.py`, `qa_runner.py`)

- [x] 2.1 RED: `build_repro_prompt` signature has no diff/files/commit parameter (`inspect.signature`); rendered prompt contains the isolation clause and the confirmed db/url; no `_answer_block`/`_default_config_block`.
- [x] 2.2 GREEN: modify `build_repro_prompt(run_dir, ticket_id, ticket_history, env)` — add `_DB_ACCESS_RULE`, `_confirmed_env_block(env)`, anti-lookup clause forbidding `git log/diff/show/blame`.
- [x] 2.3 RED: `REPRO_SCHEMA` accepts `status: "blocked"` + `blocked_reason`; `not_reproduced` with empty `steps[]` normalises to `blocked`/`repro_no_attempt_evidence`.
- [x] 2.4 GREEN: extend `REPRO_SCHEMA` enum in `qa_orchestrator.py`; add `_repro_blocked(repro) -> str|None` in `qa_runner.py`; normalise empty-steps case.
- [x] 2.5 RED (integration): repro `blocked` ⇒ pause once via env channel (`clear_env_context` + `_finalize_awaiting_input(topic="env")` seeded with `blocked_reason`) ⇒ still blocked on retry ⇒ falls through to `manual_review`, never `dudoso`, never a correction.
- [x] 2.6 GREEN: implement `MAX_BLOCKED_REPRO_PAUSES = 1` bound and routing in `run_pipeline()`; preserve `status["repro_blocked_pauses"]` via `resume_qa`'s `{**status, ...}` merge.

## Phase 3: Combined Review Stage + Aggregator Security Gate (`qa_orchestrator.py`, `qa_prompts.py`, `qa_runner.py`)

- [x] 3.1 GREEN: add `BLOCKING_SECURITY_CATEGORIES` frozenset (10 entries: sql_injection, command_injection, path_traversal, unsafe_deserialization, credential_exposure, sensitive_data_exposure, auth_bypass, authorization_bypass, xss, ssrf) and `REVIEW_SCHEMA` (`qa.review/1`) in `qa_orchestrator.py`.
- [x] 3.2 RED: `_blocking_security_findings` — allowlisted category blocks regardless of `severity:"low"`; unknown category never blocks even at `severity:"severe"`; quality findings never block.
- [x] 3.3 GREEN: implement `_blocking_security_findings(review)` in `qa_runner.py`.
- [x] 3.4 RED (threat matrix — diff scope blowout): empty `archivos_tocados` ⇒ no `claude -p` subprocess call, `review.json status:"skipped"`, verdict still `passed`.
- [x] 3.5 RED (threat matrix — git repository selection): fake `_git` recorder asserts every argv is read-only (`merge-base`/`diff`) and every `cwd == project_path`.
- [x] 3.6 RED (threat matrix — push state): extend existing `_git` denylist tests to assert `_review_diff` never constructs a denylisted argv.
- [x] 3.7 GREEN: implement `_review_diff(project_path, archivos_tocados) -> str` — read-only `merge-base` over `("main","master","develop")` with working-tree-diff fallback; short-circuits to `""` on empty list.
- [x] 3.8 RED (threat matrix — commit state, throwaway `git init` repo): a full review run leaves index and HEAD byte-identical.
- [x] 3.9 GREEN: add `REVIEW_CONDUCT_RULES` (read-only, never edit/commit/migrate) and `build_review_prompt(run_dir, ticket_id, archivos_tocados, git_diff)` in `qa_prompts.py`.
- [x] 3.10 GREEN: implement `run_review_stage(run_dir, project_path, ticket_id, archivos_tocados) -> dict` in `qa_runner.py` via `invoke_stage()`, honoring the empty-files short-circuit and error handling.
- [x] 3.11 GREEN: implement `_review_applies(verify, regression) -> bool` (`verify.status=="pass" and regression.status in ("pass","skipped")`); wire the review block into `run_pipeline()` after regression, immediately before `aggregate()`.
- [x] 3.12 RED (integration): `run_pipeline` invokes `review_fn` exactly once on the passing path and zero times when regression fails.
- [x] 3.13 GREEN: extend `aggregate(*, repro, verify, regression, attempts, commits, review=None)` — review `error` ⇒ `manual_review`/`review_stage_error`; any blocking finding ⇒ `manual_review`/`security_finding_severe`; confirm `aggregate()` called without `review=` behaves exactly as today.
- [x] 3.14 RED (threat matrix — prompt injection via ticket data): review JSON with `severity:"none"` on an allowlisted category still blocks; an invented category never blocks.
- [x] 3.15 GREEN: extend verdict plumbing — `verdict.json.stages` gains `"review"`; `reason` gains `security_finding_severe`/`review_stage_error`/`repro_blocked`/`repro_no_attempt_evidence`; `status.json.state` gains `"review"`; thread `review=` through `_write_evidence_log`/`_finalize`.
- [x] 3.16 RED: unit — full aggregator truth-table additions in one place (`blocked` ⇒ `manual_review`; empty-steps `not_reproduced` ⇒ `repro_no_attempt_evidence`; review error ⇒ `manual_review`; pre-existing behavior unchanged).

## Phase 4: Subprocess Hardening + Full-Suite Regression

- [x] 4.1 RED (threat matrix — subprocess/shell composition): env answer containing a backtick, semicolon, newline, and a 5000-char string ⇒ rejected by `_parse_env_answer`, question re-asked, `invoke_stage` argv (`[exe, "-p", "Read <path> …"]`, `shell=False`) unchanged.
- [x] 4.2 GREEN: close any gap found in 4.1 (expected to already pass from task 1.4 — this task exists to prove it, not to add new parsing logic). Confirmed: no gap, already green from 1.4's implementation.
- [x] 4.3 GREEN: add `run_pipeline(review_fn=...)` injectable parameter so 3.12's test double can be wired without a real `claude -p` call.
- [x] 4.4 Run full `tests/test_qa_orchestrator.py` (101 existing + all new cases) green — regression net for every addition in Phases 1–3. Result: 210/210 passing.
- [x] 4.5 Confirm `LogScreen`/evidence.log already surfaces `review.json`'s `security`/`quality` sections verbatim (qa-status-surface requirement) with zero TUI code change; if a gap is found, file it as a follow-up, not scope creep into this change. Confirmed via `ReviewFindingsEvidenceDigestTestCase` — zero TUI code touched.
